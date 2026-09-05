"""W8 — 经营分析：每日对外售价录入与成本/收入/毛利/利润率报表。

收入口径（2026-09-05 裁决）：标准收入 = 当日对外售价 × 当日结算秒数。
- 结算秒数来自 wallet_transactions（SETTLE，按任务提交分辨率分档）；
- 成本来自 generation_tasks.actual_cost（W9：秒 × 提交时费率快照）；
- 日界为 Asia/Shanghai（created_at/completed_at 存 UTC 文本，先解释为
  UTC 再转东八区取日期）。

写路径（每日售价 upsert）走共享管理写契约（T12 precedent）：真实操作人、
原因、幂等键；auditor 只读。历史无 actual_cost 的区间在报表里以
cost = NULL 呈现（口径起点标注），不回填虚构。
"""

from __future__ import annotations

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


class ProfitOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: list[DailyPriceRow]
    days: list[ProfitDayRow]
    cost_coverage_note: str


def _shanghai_day_utc_expression(column_sql: str) -> str:
    """UTC 文本时间戳 → Asia/Shanghai 日（可再 ::date 取日界）。"""
    return f"(to_timestamp({column_sql}, 'YYYY-MM-DD HH24:MI:SS') AT TIME ZONE 'Asia/Shanghai')"


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

    def business(conn: psycopg.Connection, request_id: str) -> Any:
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
        return [
            DailyPriceRow(
                price_date=row[0].isoformat(),
                price_768p_fen=int(row[1]),
                price_2k_fen=int(row[2]),
                note=row[3],
                created_by_username=row[4],
            ).model_dump()
            for row in rows
        ]

    # 快照层按 JSON 序列化业务结果；列表响应与 dict 同样可重放。
    return cast(
        list[DailyPriceRow],
        write_with_idempotency(
            request,
            response,
            actor,
            payload,
            business,
            success_status=200,
            unavailable_code=PROFIT_SERVICE_UNAVAILABLE,
            unavailable_message=PROFIT_SERVICE_UNAVAILABLE_MESSAGE,
        ),
    )


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
                  (now() - make_interval(days => %s)) AT TIME ZONE 'UTC',
                  'YYYY-MM-DD HH24:MI:SS'
              )
            GROUP BY 1, 2
            ORDER BY 1
            """,
            (lookback_days,),
        ).fetchall()

        cost_rows = conn.execute(
            f"""
            SELECT {_shanghai_day_utc_expression("t.completed_at")}::date AS day,
                   SUM(t.actual_cost) AS cost_yuan,
                   COUNT(*) AS video_count
            FROM generation_tasks t
            WHERE t.actual_cost IS NOT NULL
              AND t.status = 'SUCCEEDED'
              AND t.completed_at >= to_char(
                  (now() - make_interval(days => %s)) AT TIME ZONE 'UTC',
                  'YYYY-MM-DD HH24:MI:SS'
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
    print("DEBUG seconds_rows:", [tuple(r) for r in seconds_rows])
    print("DEBUG cost_rows:", [tuple(r) for r in cost_rows])
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

    cost_by_day: dict[str, tuple[int | None, int]] = {}
    for row in cost_rows:
        day = str(row[0])
        cost_yuan = float(row[1]) if row[1] is not None else 0.0
        cost_by_day[day] = (round(cost_yuan * 100), int(row[2]))

    all_days = sorted(set(revenue_by_day) | set(cost_by_day))
    days: list[ProfitDayRow] = []
    for day in all_days:
        revenue = revenue_by_day.get(day, 0)
        cost_entry = cost_by_day.get(day)
        cost_fen = cost_entry[0] if cost_entry else None
        gross = None if cost_fen is None else revenue - cost_fen
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
            )
        )
    days.reverse()

    return ProfitOverviewResponse(
        prices=prices,
        days=days,
        cost_coverage_note="成本自 2026-09 费率快照启用起核算；更早区间无成本数据，不回填。",
    ).model_dump()
