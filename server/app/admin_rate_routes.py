"""W10 — operation cost rates and external per-second prices (费率管理).

管理后台「系统设置 · 费率管理」页签的读写面：
- ``GET /api/control/settings/rates``（AdminReader）：按 kind 分组的费率
  表（上游成本 7 科目 + 对外售价档）与最近变更历史（audit_logs 读取）。
- ``PUT /api/control/settings/rates``（AdminWriter + 管理写契约）：批量
  调整科目单价；每次调整在业务事务内落 audit_logs（old/new + reason +
  request_id），供审计中心与费率页「历史变更」追溯。

Contract mirrors ``admin_runtime_routes``（T12 precedent）：AdminReader
reads, AdminWriter writes, every write lands an audit_logs row with the
real operator, and the SQLite lane is not applicable — the customer-domain
rate table follows migrations 027+ and admin sessions themselves require
the PostgreSQL runtime.

校验（防御性，配合前端的边界与 >50% 二次确认）：
- subject 必须在已知科目集合内（API 不能凭空造科目）；
- unit_price_fen 必须为 0..MAX_RATE_UNIT_PRICE_FEN 的整数；
- 空更新列表拒绝（避免无意义消费幂等键）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.admin_auth_routes import AdminReader, AdminWriter
from app.admin_write_contract import AdminWriteContract, write_with_idempotency
from app.db_pg import pg_transaction

router = APIRouter(prefix="/api/control", tags=["admin-rates"])

RATES_SERVICE_UNAVAILABLE = "RATES_SERVICE_UNAVAILABLE"
RATES_SERVICE_UNAVAILABLE_MESSAGE = "费率管理需要 PostgreSQL 运行时。"

RATE_UPDATE_ACTION = "operation_rate.update"
RATE_HISTORY_LIMIT = 5

# 单价上界：100 万元/单位（分），任何现实科目都远低于此；拦截手滑多打零。
MAX_RATE_UNIT_PRICE_FEN = 100_000_000

# 已知科目集合：与迁移 056 的种子一致。前端展示名映射放在客户端。
KNOWN_RATE_SUBJECTS: frozenset[str] = frozenset(
    {
        "video_generation_768p",
        "video_generation_2k",
        "video_analysis_768p",
        "video_analysis_2k",
        "first_frame_image",
        "character_sheet_image",
        "context_ir",
        "external_price_768p",
        "external_price_2k",
    }
)


class RateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    kind: Literal["upstream_cost", "external_price"]
    unit: Literal["second", "image", "call"]
    resolution: str | None
    unit_price_fen: int
    updated_at: str
    updated_by_username: str | None


class RateHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    old_unit_price_fen: int | None
    new_unit_price_fen: int
    reason: str
    actor_username: str | None
    created_at: str


class RatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rates: list[RateEntry]
    history: list[RateHistoryEntry]


class RateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    unit_price_fen: int = Field(ge=0, le=MAX_RATE_UNIT_PRICE_FEN)


class RatesUpdateRequest(AdminWriteContract):
    """费率调整走共享管理写契约（T12 precedent）：幂等键、confirm、原因。"""

    model_config = ConfigDict(extra="forbid")

    updates: list[RateUpdate] = Field(min_length=1)


def _read_rates(conn: psycopg.Connection) -> list[RateEntry]:
    rows = conn.execute(
        """
        SELECT r.subject, r.kind, r.unit, r.resolution, r.unit_price_fen,
               r.updated_at, u.username AS updated_by_username
        FROM operation_cost_rates r
        LEFT JOIN users u ON u.id = r.updated_by_user_id
        ORDER BY r.kind, r.subject
        """
    ).fetchall()
    return [
        RateEntry(
            subject=row[0],
            kind=row[1],
            unit=row[2],
            resolution=row[3],
            unit_price_fen=int(row[4]),
            updated_at=row[5].isoformat(),
            updated_by_username=row[6],
        )
        for row in rows
    ]


def _read_history(conn: psycopg.Connection) -> list[RateHistoryEntry]:
    rows = conn.execute(
        """
        SELECT a.entity_id AS subject, a.metadata_json, a.created_at,
               u.username AS actor_username
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.actor_user_id
        WHERE a.action = %s
        ORDER BY a.created_at DESC
        LIMIT %s
        """,
        (RATE_UPDATE_ACTION, RATE_HISTORY_LIMIT),
    ).fetchall()
    entries: list[RateHistoryEntry] = []
    for row in rows:
        metadata = json.loads(row[1] or "{}")
        entries.append(
            RateHistoryEntry(
                subject=str(row[0]),
                old_unit_price_fen=metadata.get("old_unit_price_fen"),
                new_unit_price_fen=int(metadata.get("new_unit_price_fen", 0)),
                reason=str(metadata.get("reason", "")),
                actor_username=row[3],
                created_at=(row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2])),
            )
        )
    return entries


@router.get("/settings/rates", response_model=RatesResponse)
def read_rates(_actor: AdminReader) -> dict[str, Any]:
    """费率表与最近变更（审计员与管理员均可读）。"""
    with pg_transaction() as conn:
        return RatesResponse(
            rates=_read_rates(conn),
            history=_read_history(conn),
        ).model_dump()


@router.put("/settings/rates", response_model=RatesResponse)
def update_rates(
    payload: RatesUpdateRequest,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> dict[str, object]:
    """批量调整科目单价：逐科目记 audit（old/new），同事务提交。"""

    unknown = [u.subject for u in payload.updates if u.subject not in KNOWN_RATE_SUBJECTS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "RATE_SUBJECT_UNKNOWN",
                "message": f"未知费率科目：{', '.join(sorted(set(unknown)))}",
            },
        )

    def business(conn: psycopg.Connection, request_id: str) -> dict[str, object]:
        for update in payload.updates:
            old = conn.execute(
                "SELECT unit_price_fen FROM operation_cost_rates WHERE subject = %s",
                (update.subject,),
            ).fetchone()
            if old is None:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "RATE_SUBJECT_UNKNOWN",
                        "message": f"费率科目不存在：{update.subject}",
                    },
                )
            old_price = int(old[0])
            conn.execute(
                """
                UPDATE operation_cost_rates
                SET unit_price_fen = %s,
                    updated_by_user_id = %s,
                    updated_at = now()
                WHERE subject = %s
                """,
                (update.unit_price_fen, actor.user_id, update.subject),
            )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    id, actor_user_id, action, entity_type, entity_id, metadata_json
                ) VALUES (%s, %s, %s, 'operation_cost_rate', %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    actor.user_id,
                    RATE_UPDATE_ACTION,
                    update.subject,
                    json.dumps(
                        {
                            "subject": update.subject,
                            "old_unit_price_fen": old_price,
                            "new_unit_price_fen": update.unit_price_fen,
                            "reason": payload.reason.strip(),
                            "request_id": request_id,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        return RatesResponse(
            rates=_read_rates(conn),
            history=_read_history(conn),
        ).model_dump()

    return write_with_idempotency(
        request,
        response,
        actor,
        payload,
        business,
        success_status=200,
        unavailable_code=RATES_SERVICE_UNAVAILABLE,
        unavailable_message=RATES_SERVICE_UNAVAILABLE_MESSAGE,
    )
