"""Explicit, idempotent customer refreshes; opening a cached list has no fee."""

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.billing_meter import billing_context
from app.customer_fence import BusinessDbDep
from app.permissions import require_not_auditor
from app.usage_billing import accept_operation, finish_operation
from app.viral_routes import ViralStatisticsResponse, _item, get_viral_source_client
from app.viral_statistics import _fetch_detail, _has_statistics, _load_wechat_videos, _needs_refresh
from app.viral_store import update_viral_statistics

router = APIRouter(tags=["viral-billing"])


class RefreshRequest(BaseModel):
    videoIds: list[str] = Field(min_length=1, max_length=12)


@router.post("/api/viral/videos/statistics/refresh", response_model=ViralStatisticsResponse)
def refresh_statistics(
    payload: RefreshRequest,
    db: BusinessDbDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> ViralStatisticsResponse:
    ids = sorted(set(payload.videoIds))
    fingerprint = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
    with db.write() as (conn, actor):
        source = "viral-statistics:" + actor.id + ":" + idempotency_key
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("billing:user:" + actor.id,))
        require_not_auditor(
            conn,
            actor=actor,
            action="viral.statistics.refresh",
            entity_type="viral_statistics",
            entity_id=fingerprint,
        )
        old = conn.execute(
            "SELECT id,state,request_fingerprint FROM billing_operations WHERE user_id=%s "
            "AND service='viral_data' AND source_id=%s",
            (actor.id, source),
        ).fetchone()
        if old:
            if old["request_fingerprint"] != fingerprint:
                raise HTTPException(409, detail="幂等键已用于其他数据请求")
            if old["state"] == "PENDING":
                raise HTTPException(409, detail="数据请求正在处理或待核对，请勿重复提交")
            return ViralStatisticsResponse(
                items=[_item(video) for video in _load_wechat_videos(conn, ids)]
            )
        client = get_viral_source_client(conn)
        if client is None:
            raise HTTPException(503, detail="爆款数据服务尚未配置")
        videos = _load_wechat_videos(conn, ids)
        pending = [
            video for video in videos if _needs_refresh(video) and video.native.get("export_id")
        ]
        operation = accept_operation(
            conn,
            user_id=actor.id,
            service="viral_data",
            source_id=source,
            units=len(pending),
            request_fingerprint=fingerprint,
        )
    succeeded = 0
    for video in pending:
        with db.write() as (conn, _actor):
            previous = conn.execute(
                "SELECT count(*) FROM billing_attempts WHERE operation_id=%s", (operation,)
            ).fetchone()[0]
        try:
            with billing_context(source):
                detail = _fetch_detail(client, video)
        except Exception:
            continue
        with db.write() as (conn, _actor):
            calls = conn.execute(
                "SELECT count(*) FROM billing_attempts WHERE operation_id=%s", (operation,)
            ).fetchone()[0]
            if _has_statistics(detail):
                update_viral_statistics(
                    conn, platform=video.platform, video_id=video.video_id, detail=detail
                )
                # An in-process detail cache hit performs no supplier request and costs no credits.
                succeeded += min(1, calls - previous)
                conn.execute(
                    "UPDATE billing_operations SET actual_units=%s WHERE id=%s AND state='PENDING'",
                    (succeeded, operation),
                )
    with db.write() as (conn, _actor):
        finish_operation(conn, operation_id=operation, units=succeeded, succeeded=True)
        return ViralStatisticsResponse(
            items=[_item(video) for video in _load_wechat_videos(conn, ids)]
        )
