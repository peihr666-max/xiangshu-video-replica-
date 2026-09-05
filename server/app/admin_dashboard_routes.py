"""W15 — 总览仪表盘聚合端点（AdminReader 只读）。

一次性返回仪表盘所需的全部计数（避免前端拼十几个请求）：
- 今日生成数 / 成功数（Asia/Shanghai 日界，沿用 042 的 created_at_utc）；
- 在线设备（会话租约未过期的去重设备数）；
- 活跃客户（role=customer 且 is_active 的用户数）；
- 今日充值合计（PAID 订单金额，按 paid_at 的上海日界）；
- 近 7 日生成趋势（按日成功/失败）；
- 待办四项：待批准配对（PENDING 且未过期）、近 7 日失败任务、
  对账不一致合计（复用 billing-reconciliation 口径）、7 天内即将过期激活码；
- 设备槽位占用（BOUND 设备数 / 客户数 × 2）。

只读聚合，无写路径；PostgreSQL-only（客户域，027+ 同）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.admin_auth_routes import AdminReader
from app.db_pg import pg_transaction

router = APIRouter(prefix="/api/control", tags=["admin-dashboard"])

# 上海日界表达式：timestamptz → 上海挂钟日期文本
_SHANGHAI_DATE = "(%s AT TIME ZONE 'Asia/Shanghai')::date"


def _one(conn: Any, sql: str) -> Any:
    """单值聚合查询：fetchone 保证非空（聚合无 GROUP BY 恒返一行）。"""
    row = conn.execute(sql).fetchone()
    assert row is not None
    return row[0]


def _day_expr(column: str) -> str:
    return _SHANGHAI_DATE % f"{column} AT TIME ZONE 'UTC'"


@router.get("/dashboard/summary")
def dashboard_summary(_actor: AdminReader) -> dict[str, Any]:
    with pg_transaction() as conn:
        today_generation = conn.execute(
            f"""
            SELECT count(*) AS total,
                   count(*) FILTER (
                       WHERE status = 'SUCCEEDED'
                         AND archive_status IN ('ARCHIVED', 'DIRECT')
                   ) AS succeeded
            FROM generation_tasks
            WHERE {_day_expr("created_at_utc")} = {_day_expr("now()")}
            """
        ).fetchone()
        assert today_generation is not None

        trend_rows = conn.execute(
            f"""
            SELECT {_day_expr("created_at_utc")} AS day,
                   count(*) FILTER (
                       WHERE status = 'SUCCEEDED'
                         AND archive_status IN ('ARCHIVED', 'DIRECT')
                   ) AS succeeded,
                   count(*) FILTER (WHERE status = 'FAILED') AS failed
            FROM generation_tasks
            WHERE created_at_utc >= (now() - make_interval(days => 6))
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchall()

        online_devices = int(
            _one(
                conn,
                """
                SELECT count(DISTINCT device_id) FROM customer_session_state
                WHERE lease_until::timestamptz > now()
                """,
            )
        )
        active_customers = int(
            _one(
                conn,
                """
                SELECT count(*) FROM users
                WHERE role = 'customer' AND is_active = 1
                """,
            )
        )
        today_recharge_fen = int(
            _one(
                conn,
                f"""
                SELECT COALESCE(SUM(amount_fen), 0) FROM recharge_orders
                WHERE status = 'PAID'
                  AND paid_at IS NOT NULL
                  AND {_SHANGHAI_DATE % "paid_at::timestamp"} = {_day_expr("now()")}
                """,
            )
        )

        pending_pairings = int(
            _one(
                conn,
                """
                SELECT count(*) FROM device_pairing_requests
                WHERE status = 'PENDING' AND expires_at::timestamptz > now()
                """,
            )
        )
        failed_tasks_7d = int(
            _one(
                conn,
                """
                SELECT count(*) FROM generation_tasks
                WHERE status = 'FAILED'
                  AND created_at_utc >= (now() - make_interval(days => 7))
                """,
            )
        )
        expiring_codes = int(
            _one(
                conn,
                """
                SELECT count(*) FROM activation_codes c
                JOIN activation_code_batches b ON b.id = c.batch_id
                WHERE c.status IN ('GENERATED', 'ISSUED')
                  AND b.activation_expires_at::timestamptz >= now()
                  AND b.activation_expires_at::timestamptz < now() + make_interval(days => 7)
                """,
            )
        )
        reconciliation_problems = int(
            _one(
                conn,
                """
                SELECT
                  (SELECT count(*) FROM wallets w
                     WHERE w.available_credits + w.reserved_credits <>
                           COALESCE((SELECT SUM(available_delta + reserved_delta)
                             FROM wallet_transactions wt WHERE wt.user_id = w.user_id), 0))
                + (SELECT count(*) FROM recharge_orders o
                     WHERE o.status = 'PAID' AND NOT EXISTS (
                         SELECT 1 FROM wallet_transactions wt
                         WHERE wt.recharge_order_id = o.id AND wt.type = 'CHARGE'))
                + (SELECT count(*) FROM wallet_transactions wt
                     WHERE wt.type = 'CHARGE' AND NOT EXISTS (
                         SELECT 1 FROM recharge_orders o
                         WHERE o.id = wt.recharge_order_id AND o.status = 'PAID'))
                """,
            )
        )
        bound_devices = int(
            _one(
                conn,
                "SELECT count(*) FROM customer_devices WHERE status = 'BOUND'",
            )
        )

    trend = [
        {"day": str(row[0]), "succeeded": int(row[1]), "failed": int(row[2])} for row in trend_rows
    ]
    return {
        "today": {
            "generation_count": int(today_generation[0]),
            "succeeded": int(today_generation[1]),
            "online_devices": online_devices,
            "active_customers": active_customers,
            "recharge_fen": today_recharge_fen,
        },
        "trend": trend,
        "todos": {
            "pending_pairings": pending_pairings,
            "failed_tasks_7d": failed_tasks_7d,
            "reconciliation_problems": reconciliation_problems,
            "expiring_codes_7d": expiring_codes,
        },
        "device_slots": {
            "bound": bound_devices,
            "total": active_customers * 2,
        },
    }
