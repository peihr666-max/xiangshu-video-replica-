"""按提交时长为视频生成预留和结算秒数，同时保留口播账务形状。

Revision ID: 065_second_based_billing
Revises: 064_operation_cost_rates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "065_second_based_billing"
down_revision = "064_operation_cost_rates"
branch_labels = None
depends_on = None

_OLD_SHAPE = (
    "(type = 'CHARGE' AND available_delta > 0 AND reserved_delta = 0 "
    "AND recharge_order_id IS NOT NULL AND task_id IS NULL "
    "AND oral_task_id IS NULL AND billing_round IS NULL) OR "
    "(type = 'RESERVE' AND available_delta = -1 AND reserved_delta = 1 "
    "AND recharge_order_id IS NULL AND (task_id IS NULL) <> (oral_task_id IS NULL) "
    "AND billing_round IS NOT NULL) OR "
    "(type = 'SETTLE' AND available_delta = 0 AND reserved_delta = -1 "
    "AND recharge_order_id IS NULL AND (task_id IS NULL) <> (oral_task_id IS NULL) "
    "AND billing_round IS NOT NULL) OR "
    "(type = 'RELEASE' AND available_delta = 1 AND reserved_delta = -1 "
    "AND recharge_order_id IS NULL AND (task_id IS NULL) <> (oral_task_id IS NULL) "
    "AND billing_round IS NOT NULL)"
)

_NEW_SHAPE = (
    "(type = 'CHARGE' AND available_delta > 0 AND reserved_delta = 0 "
    "AND recharge_order_id IS NOT NULL AND task_id IS NULL "
    "AND oral_task_id IS NULL AND billing_round IS NULL) OR "
    "(type = 'RESERVE' AND recharge_order_id IS NULL AND billing_round IS NOT NULL AND ("
    "(task_id IS NOT NULL AND oral_task_id IS NULL "
    "AND available_delta = -reserved_delta AND reserved_delta >= 1) OR "
    "(task_id IS NULL AND oral_task_id IS NOT NULL "
    "AND available_delta = -1 AND reserved_delta = 1))) OR "
    "(type = 'SETTLE' AND recharge_order_id IS NULL AND billing_round IS NOT NULL AND ("
    "(task_id IS NOT NULL AND oral_task_id IS NULL "
    "AND available_delta = 0 AND reserved_delta <= -1) OR "
    "(task_id IS NULL AND oral_task_id IS NOT NULL "
    "AND available_delta = 0 AND reserved_delta = -1))) OR "
    "(type = 'RELEASE' AND recharge_order_id IS NULL AND billing_round IS NOT NULL AND ("
    "(task_id IS NOT NULL AND oral_task_id IS NULL "
    "AND available_delta = -reserved_delta AND reserved_delta <= -1) OR "
    "(task_id IS NULL AND oral_task_id IS NOT NULL "
    "AND available_delta = 1 AND reserved_delta = -1)))"
)


def _replace_shape(shape: str) -> None:
    with op.batch_alter_table("wallet_transactions") as batch_op:
        batch_op.drop_constraint("ck_wallet_transactions_shape", type_="check")
        batch_op.create_check_constraint("ck_wallet_transactions_shape", shape)


def upgrade() -> None:
    _replace_shape(_NEW_SHAPE)
    op.add_column(
        "generation_tasks",
        sa.Column(
            "billed_seconds",
            sa.Integer(),
            nullable=True,
            comment="提交时冻结的客户计费秒数；NULL 表示历史每轮一条",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    non_unit = bind.execute(
        sa.text(
            "SELECT 1 FROM wallet_transactions WHERE task_id IS NOT NULL "
            "AND (reserved_delta NOT IN (-1, 1) OR available_delta NOT IN (-1, 0, 1)) LIMIT 1"
        )
    ).first()
    billed = bind.execute(
        sa.text("SELECT 1 FROM generation_tasks WHERE billed_seconds > 1 LIMIT 1")
    ).first()
    if non_unit or billed:
        raise RuntimeError(
            "cannot downgrade 065 while second-based generation billing exists; "
            "preserve and reconcile the wallet ledger first"
        )
    op.drop_column("generation_tasks", "billed_seconds")
    _replace_shape(_OLD_SHAPE)
