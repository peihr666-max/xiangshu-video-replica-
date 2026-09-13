"""Operation-level economics; unknown evidence never becomes zero profit."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.db_portable import BusinessConnection


def date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    if end < start:
        raise HTTPException(422, detail="结束日期不能早于开始日期")
    zone = ZoneInfo("Asia/Shanghai")
    return datetime.combine(start, time.min, zone), datetime.combine(
        end + timedelta(days=1), time.min, zone
    )


def operation_rows(
    conn: BusinessConnection,
    *,
    start: date,
    end: date,
    user_id: str | None = None,
    service: str | None = None,
    module: str | None = None,
    provider: str | None = None,
    limit: int = 5000,
    offset: int = 0,
    operation_id: str | None = None,
) -> list[dict[str, Any]]:
    lower, upper = date_bounds(start, end)
    # Aggregate provider attempts before joining the single revenue fact.
    rows = conn.execute(
        """
        SELECT o.*, COALESCE(u.username,'平台后台') AS username, COALESCE(c.attempt_count,0) AS attempt_count,
          COALESCE(c.known_cost_fen,0) AS known_cost_fen,
          COALESCE(c.unknown_cost_count,0) AS unknown_cost_count,
          CASE WHEN COALESCE(c.unknown_cost_count,0)=0 AND o.state<>'PENDING'
            THEN COALESCE(c.known_cost_fen,0) ELSE NULL END AS cost_fen,
          count(*) OVER() AS total_count
        FROM billing_operations o LEFT JOIN users u ON u.id=o.user_id
        LEFT JOIN (
          SELECT operation_id,count(*) AS attempt_count,sum(cost_fen) AS known_cost_fen,
            count(*) FILTER(WHERE cost_fen IS NULL) AS unknown_cost_count
          FROM billing_attempts GROUP BY operation_id
        ) c ON c.operation_id=o.id
        WHERE COALESCE(o.completed_at,o.created_at)>=%s AND COALESCE(o.completed_at,o.created_at)<%s
          AND (%s::text IS NULL OR o.user_id=%s) AND (%s::text IS NULL OR o.service=%s)
          AND (%s::text IS NULL OR o.module=%s) AND (%s::text IS NULL OR o.id=%s)
          AND (%s::text IS NULL OR EXISTS(SELECT 1 FROM billing_attempts a WHERE a.operation_id=o.id AND a.provider=%s))
        ORDER BY COALESCE(o.completed_at,o.created_at) DESC,o.id DESC LIMIT %s OFFSET %s
    """,
        (
            lower,
            upper,
            user_id,
            user_id,
            service,
            service,
            module,
            module,
            operation_id,
            operation_id,
            provider,
            provider,
            limit,
            offset,
        ),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        known = (
            item["cost_fen"] is not None
            and item["revenue_fen"] is not None
            and item["state"] != "PENDING"
        )
        item["profit_fen"] = item["revenue_fen"] - item["cost_fen"] if known else None
        result.append(item)
    return result


def statistics(
    conn: BusinessConnection,
    *,
    start: date,
    end: date,
    grain: str = "day",
    user_id: str | None = None,
    service: str | None = None,
    module: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    if grain not in {"day", "week", "month", "year"}:
        raise HTTPException(422, detail="不支持的统计周期")
    lower, upper = date_bounds(start, end)
    rows = conn.execute(
        """
        WITH costs AS (
          SELECT operation_id,count(*) AS calls,sum(cost_fen) AS known_cost,
            count(*) FILTER(WHERE cost_fen IS NULL) AS unknown_cost
          FROM billing_attempts GROUP BY operation_id
        ), facts AS (
          SELECT o.*,COALESCE(c.calls,0) AS calls,COALESCE(c.known_cost,0) AS known_cost,
            COALESCE(c.unknown_cost,0) AS unknown_cost
          FROM billing_operations o LEFT JOIN costs c ON c.operation_id=o.id
          WHERE COALESCE(o.completed_at,o.created_at)>=%s AND COALESCE(o.completed_at,o.created_at)<%s
            AND (%s::text IS NULL OR o.user_id=%s) AND (%s::text IS NULL OR o.service=%s)
            AND (%s::text IS NULL OR o.module=%s)
            AND (%s::text IS NULL OR EXISTS(SELECT 1 FROM billing_attempts a WHERE a.operation_id=o.id AND a.provider=%s))
        )
        SELECT date_trunc(%s,COALESCE(completed_at,created_at) AT TIME ZONE 'Asia/Shanghai') AS period,
          count(*) AS operation_count, count(*) FILTER(WHERE charged_credits>0) AS charged_count,
          count(*) FILTER(WHERE reserved_credits=0) AS free_count,
          count(*) FILTER(WHERE state='PENDING') AS pending_count,
          sum(calls) AS provider_call_count, sum(charged_credits) AS charged_credits,
          sum(CASE WHEN state<>'PENDING' THEN reserved_credits-charged_credits ELSE 0 END) AS refunded_credits,
          sum(known_cost) AS known_cost_fen,sum(revenue_fen) AS known_revenue_fen,
          count(*) FILTER(WHERE unknown_cost>0) AS unknown_cost_count,
          count(*) FILTER(WHERE revenue_fen IS NULL) AS unknown_revenue_count,
          sum(CASE WHEN reserved_credits=0 OR (state<>'PENDING' AND charged_credits=0) THEN known_cost ELSE 0 END) AS platform_cost_fen,
          sum(CASE WHEN unit='second' THEN actual_units ELSE 0 END) AS seconds,
          sum(CASE WHEN unit='image' THEN actual_units ELSE 0 END) AS images,
          sum(CASE WHEN unit='call' THEN actual_units ELSE 0 END) AS calls
        FROM facts GROUP BY GROUPING SETS ((period),()) ORDER BY period NULLS LAST
    """,
        (
            lower,
            upper,
            user_id,
            user_id,
            service,
            service,
            module,
            module,
            provider,
            provider,
            grain,
        ),
    ).fetchall()
    items = []
    totals: dict[str, Any] = {}
    for row in rows:
        item = dict(row)
        complete = not (
            item["unknown_cost_count"] or item["unknown_revenue_count"] or item["pending_count"]
        )
        revenue = item["known_revenue_fen"] or 0
        cost = item["known_cost_fen"] or 0
        item["profit_fen"] = revenue - cost if complete else None
        item["profit_margin"] = (revenue - cost) / revenue if complete and revenue else None
        if item["period"] is None:
            totals = item
        else:
            item["period"] = item["period"].date().isoformat()
            items.append(item)
    return {
        "timezone": "Asia/Shanghai",
        "grain": grain,
        "start": start,
        "end": end,
        "totals": totals,
        "periods": items,
        "basis": "请求结算归属周期；未结算请求按受理时间列示。成本或收入证据未齐时利润待核对。",
    }
