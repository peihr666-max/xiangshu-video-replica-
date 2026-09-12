"""W8 — 经营分析：每日对外售价录入与成本/收入/毛利/利润率报表。

收入口径（2026-09-05 裁决）：标准收入 = 当日对外售价 × 当日结算秒数。
- 结算秒数来自 wallet_transactions（SETTLE，按任务提交分辨率分档）；
- 成本来自 operation_cost_records（W9：真实用量 × 提交时费率快照）；
- 日界为 Asia/Shanghai（created_at/completed_at 存 UTC 文本，先解释为
  UTC 再转东八区取日期）。

写路径（每日售价 upsert）走共享管理写契约（T12 precedent）：真实操作人、
原因、幂等键；auditor 只读。历史无成本记录的区间在报表里以
cost = NULL 呈现（口径起点标注），不回填虚构。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date
from typing import Any, cast

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.admin_auth_routes import AdminReader, AdminWriter
from app.admin_write_contract import AdminWriteContract, write_with_idempotency
from app.db_pg import pg_transaction

router = APIRouter(prefix="/api/control", tags=["admin-profit"])

PROFIT_SERVICE_UNAVAILABLE = "PROFIT_SERVICE_UNAVAILABLE"
PROFIT_SERVICE_UNAVAILABLE_MESSAGE = "经营分析需要 PostgreSQL 运行时。"

DEFAULT_PRICE_768P_FEN = 12
DEFAULT_PRICE_2K_FEN = 20
DEFAULT_LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 366


class DailyPriceUpsertRequest(AdminWriteContract):
    """每日对外售价：upsert（同日重复录入即改价），契约 + 审计。"""

    model_config = ConfigDict(extra="forbid")

    price_date: str = Field(description="生效日期 YYYY-MM-DD（Asia/Shanghai）")
    price_768p_fen: int = Field(ge=0, le=100_000_000)
    price_2k_fen: int = Field(ge=0, le=100_000_000)
    note: str = ""


class DailyPriceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_date: str
    price_768p_fen: int
    price_2k_fen: int
    note: str | None
    created_by_username: str | None


class ProfitDayRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    video_count: int
    settled_seconds: int
    revenue_fen: int
    cost_fen: int | None
    gross_fen: int | None
    margin_pct: float | None
    cost_unknown_count: int = 0


class ProfitOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: list[DailyPriceRow]
    days: list[ProfitDayRow]
    cost_coverage_note: str


class CostDayRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    video_count: int
    output_seconds: float
    video_768p_fen: float
    video_2k_fen: float
    analysis_fen: float
    image_fen: float
    context_ir_fen: float
    total_cost_fen: float
    unknown_count: int


class CostRecordRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    occurred_at: str
    source_type: str
    source_id: str
    subject: str
    resolution: str | None
    unit: str
    usage_amount: float | None
    unit_price_fen: int
    cost_fen: float | None
    status: str


class CostOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: list[CostDayRow]
    records: list[CostRecordRow]
    record_total: int
    records_truncated: bool
    total_cost_fen: float
    total_output_seconds: float
    average_video_cost_per_second_fen: float | None
    unknown_count: int


def _shanghai_day_utc_expression(column_sql: str) -> str:
    """UTC 文本时间戳 → Asia/Shanghai 日（可再 ::date 取日界）。"""
    return f"((({column_sql})::timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Shanghai')"


def _validate_price_date(price_date: str) -> date:
    try:
        parsed = date.fromisoformat(price_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROFIT_DATE_INVALID", "message": "日期格式需为 YYYY-MM-DD"},
        ) from exc
    return parsed


@router.get("/settings/rates/history", response_model=list[DailyPriceRow])
def list_daily_prices(
    _actor: AdminReader,
    limit: int = Query(default=30, ge=1, le=366),
) -> list[DailyPriceRow]:
    """已录入的每日对外售价（按日期倒序）。"""
    with pg_transaction() as conn:
        rows = conn.execute(
            """
            SELECT p.price_date, p.price_768p_fen, p.price_2k_fen, p.note,
                   u.username AS created_by_username
            FROM daily_external_prices p
            LEFT JOIN users u ON u.id = p.created_by_user_id
            ORDER BY p.price_date DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        DailyPriceRow(
            price_date=row[0].isoformat(),
            price_768p_fen=int(row[1]),
            price_2k_fen=int(row[2]),
            note=row[3],
            created_by_username=row[4],
        )
        for row in rows
    ]


@router.put("/profit/daily-price", response_model=list[DailyPriceRow])
def upsert_daily_price(
    payload: DailyPriceUpsertRequest,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> list[DailyPriceRow]:
    """录入/更新某日的对外售价（写契约 + 审计 + 返回最新价格列表）。"""
    price_date = _validate_price_date(payload.price_date)
    if (price_date - date.today()).days > 7:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "PROFIT_DATE_TOO_FAR",
                "message": "生效日期最多允许提前 7 天录入",
            },
        )

    def business(conn: psycopg.Connection, request_id: str) -> dict[str, object]:
        conn.execute(
            """
            INSERT INTO daily_external_prices (
                price_date, price_768p_fen, price_2k_fen, note,
                created_by_user_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (price_date) DO UPDATE SET
                price_768p_fen = excluded.price_768p_fen,
                price_2k_fen = excluded.price_2k_fen,
                note = excluded.note,
                created_by_user_id = excluded.created_by_user_id,
                created_at = now()
            """,
            (
                price_date,
                payload.price_768p_fen,
                payload.price_2k_fen,
                payload.note.strip() or None,
                actor.user_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO audit_logs (
                id, actor_user_id, action, entity_type, entity_id, metadata_json
            ) VALUES (%s, %s, 'profit.daily_price.upsert', 'daily_external_prices', %s, %s)
            """,
            (
                str(uuid.uuid4()),
                actor.user_id,
                price_date.isoformat(),
                json.dumps(
                    {
                        "price_date": price_date.isoformat(),
                        "price_768p_fen": payload.price_768p_fen,
                        "price_2k_fen": payload.price_2k_fen,
                        "note": payload.note.strip() or None,
                        "reason": payload.reason.strip(),
                        "request_id": request_id,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        rows = conn.execute(
            """
            SELECT p.price_date, p.price_768p_fen, p.price_2k_fen, p.note,
                   u.username AS created_by_username
            FROM daily_external_prices p
            LEFT JOIN users u ON u.id = p.created_by_user_id
            ORDER BY p.price_date DESC
            LIMIT 60
            """
        ).fetchall()
        prices = [
            DailyPriceRow(
                price_date=row[0].isoformat(),
                price_768p_fen=int(row[1]),
                price_2k_fen=int(row[2]),
                note=row[3],
                created_by_username=row[4],
            ).model_dump()
            for row in rows
        ]
        return {"prices": prices, "request_id": request_id}

    # Keep the public list DTO; store its request id in the internal envelope
    # so a lost-response replay retains the original audit correlation.
    result = write_with_idempotency(
        request,
        response,
        actor,
        payload,
        business,
        success_status=200,
        unavailable_code=PROFIT_SERVICE_UNAVAILABLE,
        unavailable_message=PROFIT_SERVICE_UNAVAILABLE_MESSAGE,
    )
    # Compatibility with already-committed bare-list snapshots.
    return cast(list[DailyPriceRow], result if isinstance(result, list) else result["prices"])


@router.get("/profit/overview", response_model=ProfitOverviewResponse)
def profit_overview(
    _actor: AdminReader,
    lookback_days: int = Query(default=DEFAULT_LOOKBACK_DAYS, ge=1, le=MAX_LOOKBACK_DAYS),
) -> dict[str, Any]:
    """日维度收入/成本/毛利/利润率（标准收入口径，Asia/Shanghai 日界）。"""
    with pg_transaction() as conn:
        price_rows = conn.execute(
            """
            SELECT price_date, price_768p_fen, price_2k_fen, note,
                   u.username AS created_by_username
            FROM daily_external_prices p
            LEFT JOIN users u ON u.id = p.created_by_user_id
            ORDER BY price_date DESC
            LIMIT 366
            """
        ).fetchall()

        seconds_rows = conn.execute(
            f"""
            SELECT {_shanghai_day_utc_expression("wt.created_at")}::date AS day,
                   COALESCE(
                       NULLIF(t.prompt_snapshot_json::json ->> 'resolution', ''),
                       '768P'
                   ) AS resolution,
                   SUM(-wt.reserved_delta) AS settled_seconds,
                   COUNT(DISTINCT wt.task_id) AS video_count
            FROM wallet_transactions wt
            JOIN generation_tasks t ON t.id = wt.task_id
            WHERE wt.type = 'SETTLE'
              AND wt.created_at >= to_char(
                  (((
                      (now() AT TIME ZONE 'Asia/Shanghai')::date - (%s - 1)
                  )::timestamp AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'UTC'),
                  'YYYY-MM-DD HH24:MI:SS'
              )
            GROUP BY 1, 2
            ORDER BY 1
            """,
            (lookback_days,),
        ).fetchall()

        cost_rows = conn.execute(
            """
            SELECT (r.occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS day,
                   SUM(r.cost_fen) AS cost_fen,
                   COUNT(*) FILTER (WHERE r.source_type = 'generation_task') AS video_count,
                   COUNT(*) FILTER (WHERE r.status = 'UNKNOWN') AS unknown_count
            FROM operation_cost_records r
            WHERE r.occurred_at >= (
                ((now() AT TIME ZONE 'Asia/Shanghai')::date - (%s - 1))::timestamp
                AT TIME ZONE 'Asia/Shanghai'
            )
            GROUP BY 1
            ORDER BY 1
            """,
            (lookback_days,),
        ).fetchall()

    prices: list[DailyPriceRow] = [
        DailyPriceRow(
            price_date=row[0].isoformat(),
            price_768p_fen=int(row[1]),
            price_2k_fen=int(row[2]),
            note=row[3],
            created_by_username=row[4],
        )
        for row in price_rows
    ]

    # 当日售价缺失时沿用此前最近一次录入（carry-forward），避免报表断档。
    price_by_day = {row.price_date: row for row in prices}
    sorted_days = sorted(price_by_day)

    def effective_price(day: str, field: str) -> int | None:
        candidates = [d for d in sorted_days if d <= day]
        if not candidates:
            return None
        return int(getattr(price_by_day[candidates[-1]], field))

    revenue_by_day: dict[str, int] = {}
    seconds_by_day: dict[str, int] = {}
    videos_by_day: dict[str, int] = {}
    for row in seconds_rows:
        day = str(row[0])
        resolution = "2K" if str(row[1]) == "2K" else "768P"
        seconds = int(row[2])
        # 秒数与条数始终累计；售价缺失（当日未录入且此前无录入）时收入记 0，
        # 让「有成本无收入」如实暴露在报表里，而不是把当天从报表里藏掉。
        seconds_by_day[day] = seconds_by_day.get(day, 0) + seconds
        videos_by_day[day] = videos_by_day.get(day, 0) + int(row[3])
        price_field = "price_2k_fen" if resolution == "2K" else "price_768p_fen"
        price = effective_price(day, price_field)
        if price is None:
            continue
        revenue_by_day[day] = revenue_by_day.get(day, 0) + seconds * price

    cost_by_day: dict[str, tuple[int | None, int, int]] = {}
    for row in cost_rows:
        day = str(row[0])
        cost_fen = None if row[1] is None else round(float(row[1]))
        cost_by_day[day] = (cost_fen, int(row[2]), int(row[3]))

    all_days = sorted(set(seconds_by_day) | set(cost_by_day))
    days: list[ProfitDayRow] = []
    for day in all_days:
        revenue = revenue_by_day.get(day, 0)
        cost_entry = cost_by_day.get(day)
        cost_fen = cost_entry[0] if cost_entry else None
        unknown_costs = cost_entry[2] if cost_entry else 0
        gross = None if cost_fen is None or unknown_costs > 0 else revenue - cost_fen
        margin = None if gross is None or revenue == 0 else round(gross / revenue * 100, 1)
        days.append(
            ProfitDayRow(
                day=day,
                video_count=videos_by_day.get(day, cost_entry[1] if cost_entry else 0),
                settled_seconds=seconds_by_day.get(day, 0),
                revenue_fen=revenue,
                cost_fen=cost_fen,
                gross_fen=gross,
                margin_pct=margin,
                cost_unknown_count=unknown_costs,
            )
        )
    days.reverse()

    return ProfitOverviewResponse(
        prices=prices,
        days=days,
        cost_coverage_note="成本自 2026-09 费率快照启用起核算；更早区间无成本数据，不回填。",
    ).model_dump()


@router.get("/profit/overview.csv")
def export_profit_csv(
    actor: AdminReader,
    lookback_days: int = Query(default=DEFAULT_LOOKBACK_DAYS, ge=1, le=MAX_LOOKBACK_DAYS),
) -> Response:
    payload = ProfitOverviewResponse.model_validate(
        profit_overview(actor, lookback_days=lookback_days)
    )
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["日期", "结算秒数", "收入(分)", "成本(分)", "毛利(分)", "利润率", "视频数", "未知成本数"]
    )
    for row in payload.days:
        writer.writerow(
            [
                row.day,
                row.settled_seconds,
                row.revenue_fen,
                "" if row.cost_fen is None else row.cost_fen,
                "" if row.gross_fen is None else row.gross_fen,
                "" if row.margin_pct is None else row.margin_pct,
                row.video_count,
                row.cost_unknown_count,
            ]
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=profit-overview.csv"},
    )


def _cost_where(
    *, lookback_days: int, subject: str | None, resolution: str | None
) -> tuple[str, list[object]]:
    clauses = [
        "occurred_at >= ("
        "((now() AT TIME ZONE 'Asia/Shanghai')::date - (%s - 1))::timestamp "
        "AT TIME ZONE 'Asia/Shanghai'"
        ")"
    ]
    params: list[object] = [lookback_days]
    if subject:
        clauses.append("subject = %s")
        params.append(subject)
    if resolution:
        clauses.append("resolution = %s")
        params.append(resolution.upper())
    return " AND ".join(clauses), params


def _read_cost_overview(
    *, lookback_days: int, subject: str | None, resolution: str | None
) -> CostOverviewResponse:
    where_sql, params = _cost_where(
        lookback_days=lookback_days, subject=subject, resolution=resolution
    )
    with pg_transaction() as conn:
        record_total_row = conn.execute(
            f"SELECT count(*) FROM operation_cost_records WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        assert record_total_row is not None
        record_total = int(record_total_row[0])
        rows = conn.execute(
            f"""
            SELECT id, occurred_at, source_type, source_id, subject, resolution,
                   unit, usage_amount, unit_price_fen, cost_fen, status
            FROM operation_cost_records
            WHERE {where_sql}
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1000
            """,
            tuple(params),
        ).fetchall()
        day_rows = conn.execute(
            f"""
            SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS day,
                   COUNT(*) FILTER (
                       WHERE subject IN ('video_generation_768p', 'video_generation_2k')
                         AND status = 'ACTUAL'
                   ),
                   COALESCE(SUM(usage_amount) FILTER (
                       WHERE subject IN ('video_generation_768p', 'video_generation_2k')
                         AND status = 'ACTUAL'
                   ), 0),
                   COALESCE(SUM(cost_fen) FILTER (WHERE subject = 'video_generation_768p'), 0),
                   COALESCE(SUM(cost_fen) FILTER (WHERE subject = 'video_generation_2k'), 0),
                   COALESCE(SUM(cost_fen) FILTER (WHERE subject LIKE 'video_analysis_%%'), 0),
                   COALESCE(SUM(cost_fen) FILTER (
                       WHERE subject IN ('first_frame_image', 'character_sheet_image')
                   ), 0),
                   COALESCE(SUM(cost_fen) FILTER (WHERE subject = 'context_ir'), 0),
                   COALESCE(SUM(cost_fen), 0),
                   COUNT(*) FILTER (WHERE status = 'UNKNOWN')
            FROM operation_cost_records
            WHERE {where_sql}
            GROUP BY 1
            ORDER BY 1 DESC
            """,
            tuple(params),
        ).fetchall()
    records = [
        CostRecordRow(
            id=str(row[0]),
            occurred_at=row[1].isoformat(),
            source_type=str(row[2]),
            source_id=str(row[3]),
            subject=str(row[4]),
            resolution=None if row[5] is None else str(row[5]),
            unit=str(row[6]),
            usage_amount=None if row[7] is None else float(row[7]),
            unit_price_fen=int(row[8]),
            cost_fen=None if row[9] is None else float(row[9]),
            status=str(row[10]),
        )
        for row in rows
    ]
    days = [
        CostDayRow(
            day=row[0].isoformat(),
            video_count=int(row[1]),
            output_seconds=float(row[2]),
            video_768p_fen=float(row[3]),
            video_2k_fen=float(row[4]),
            analysis_fen=float(row[5]),
            image_fen=float(row[6]),
            context_ir_fen=float(row[7]),
            total_cost_fen=float(row[8]),
            unknown_count=int(row[9]),
        )
        for row in day_rows
    ]
    total_cost = sum(day.total_cost_fen for day in days)
    total_video_cost = sum(day.video_768p_fen + day.video_2k_fen for day in days)
    total_seconds = sum(day.output_seconds for day in days)
    return CostOverviewResponse(
        days=days,
        records=records,
        record_total=record_total,
        records_truncated=record_total > len(records),
        total_cost_fen=total_cost,
        total_output_seconds=total_seconds,
        average_video_cost_per_second_fen=(
            None if total_seconds == 0 else round(total_video_cost / total_seconds, 4)
        ),
        unknown_count=sum(day.unknown_count for day in days),
    )


@router.get("/profit/costs", response_model=CostOverviewResponse)
def cost_overview(
    _actor: AdminReader,
    lookback_days: int = Query(default=DEFAULT_LOOKBACK_DAYS, ge=1, le=MAX_LOOKBACK_DAYS),
    subject: str | None = Query(default=None),
    resolution: str | None = Query(default=None),
) -> dict[str, Any]:
    return _read_cost_overview(
        lookback_days=lookback_days, subject=subject, resolution=resolution
    ).model_dump()


@router.get("/profit/costs.csv")
def export_costs_csv(
    _actor: AdminReader,
    lookback_days: int = Query(default=DEFAULT_LOOKBACK_DAYS, ge=1, le=MAX_LOOKBACK_DAYS),
    subject: str | None = Query(default=None),
    resolution: str | None = Query(default=None),
) -> Response:
    payload = _read_cost_overview(
        lookback_days=lookback_days, subject=subject, resolution=resolution
    )
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "日期",
            "视频数",
            "输出秒数",
            "768P生成成本(分)",
            "2K生成成本(分)",
            "解析成本(分)",
            "图片成本(分)",
            "Context IR成本(分)",
            "合计成本(分)",
            "未知用量数",
        ]
    )
    for row in payload.days:
        writer.writerow(
            [
                row.day,
                row.video_count,
                row.output_seconds,
                row.video_768p_fen,
                row.video_2k_fen,
                row.analysis_fen,
                row.image_fen,
                row.context_ir_fen,
                row.total_cost_fen,
                row.unknown_count,
            ]
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=operation-costs.csv"},
    )
