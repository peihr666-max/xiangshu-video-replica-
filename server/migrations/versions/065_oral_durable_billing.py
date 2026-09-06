"""Add durable oral-task lifecycle and wallet references.

Revision ID: 065_oral_durable_billing
Revises: 064_oral_clone_consent
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "065_oral_durable_billing"
down_revision = "064_oral_clone_consent"
branch_labels = None
depends_on = None


_WALLET_SHAPE_WITH_ORAL = """
(type = 'CHARGE' AND available_delta > 0 AND reserved_delta = 0
 AND recharge_order_id IS NOT NULL AND task_id IS NULL AND oral_task_id IS NULL
 AND billing_round IS NULL) OR
(type = 'RESERVE' AND available_delta = -1 AND reserved_delta = 1
 AND recharge_order_id IS NULL AND ((task_id IS NOT NULL) <> (oral_task_id IS NOT NULL))
 AND billing_round IS NOT NULL) OR
(type = 'SETTLE' AND available_delta = 0 AND reserved_delta = -1
 AND recharge_order_id IS NULL AND ((task_id IS NOT NULL) <> (oral_task_id IS NOT NULL))
 AND billing_round IS NOT NULL) OR
(type = 'RELEASE' AND available_delta = 1 AND reserved_delta = -1
 AND recharge_order_id IS NULL AND ((task_id IS NOT NULL) <> (oral_task_id IS NOT NULL))
 AND billing_round IS NOT NULL)
"""

_WALLET_SHAPE_LEGACY = """
(type = 'CHARGE' AND available_delta > 0 AND reserved_delta = 0
 AND recharge_order_id IS NOT NULL AND task_id IS NULL AND billing_round IS NULL) OR
(type = 'RESERVE' AND available_delta = -1 AND reserved_delta = 1
 AND recharge_order_id IS NULL AND task_id IS NOT NULL AND billing_round IS NOT NULL) OR
(type = 'SETTLE' AND available_delta = 0 AND reserved_delta = -1
 AND recharge_order_id IS NULL AND task_id IS NOT NULL AND billing_round IS NOT NULL) OR
(type = 'RELEASE' AND available_delta = 1 AND reserved_delta = -1
 AND recharge_order_id IS NULL AND task_id IS NOT NULL AND billing_round IS NOT NULL)
"""


def upgrade() -> None:
    for table in ("oral_avatars", "oral_voices"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("lease_owner", sa.Text()))
            batch_op.add_column(sa.Column("lease_expires_at", sa.Text()))
            batch_op.add_column(sa.Column("next_attempt_at", sa.Text()))
            batch_op.add_column(
                sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
            )
            batch_op.drop_constraint(f"ck_{table}_submission_state", type_="check")
            batch_op.create_check_constraint(
                f"ck_{table}_submission_state",
                "submission_state IN ('LOCAL_PENDING', 'SUBMITTING', 'SUBMITTED', "
                "'SUBMISSION_UNKNOWN', 'FAILED')",
            )
            batch_op.create_check_constraint(f"ck_{table}_attempt_count", "attempt_count >= 0")
        op.create_index(
            f"idx_{table}_durable_claim",
            table,
            ["submission_state", "next_attempt_at", "lease_expires_at", "created_at"],
        )

    with op.batch_alter_table("wallet_transactions") as batch_op:
        batch_op.add_column(sa.Column("oral_task_id", sa.Text()))
        batch_op.create_foreign_key(
            "fk_wallet_transactions_oral_task_id",
            "oral_tasks",
            ["oral_task_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_constraint("ck_wallet_transactions_shape", type_="check")
        batch_op.create_check_constraint("ck_wallet_transactions_shape", _WALLET_SHAPE_WITH_ORAL)
    op.create_index(
        "uq_wallet_transactions_oral_reserve_round",
        "wallet_transactions",
        ["oral_task_id", "billing_round"],
        unique=True,
        sqlite_where=sa.text("type = 'RESERVE'"),
        postgresql_where=sa.text("type = 'RESERVE'"),
    )
    op.create_index(
        "uq_wallet_transactions_oral_terminal_round",
        "wallet_transactions",
        ["oral_task_id", "billing_round"],
        unique=True,
        sqlite_where=sa.text("type IN ('SETTLE', 'RELEASE')"),
        postgresql_where=sa.text("type IN ('SETTLE', 'RELEASE')"),
    )

    with op.batch_alter_table("oral_tasks") as batch_op:
        batch_op.add_column(sa.Column("billing_round", sa.Integer()))
        batch_op.add_column(sa.Column("provider_result_url", sa.Text()))
        batch_op.add_column(sa.Column("lease_owner", sa.Text()))
        batch_op.add_column(sa.Column("lease_expires_at", sa.Text()))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("next_attempt_at", sa.Text()))
        batch_op.drop_constraint("ck_oral_tasks_status", type_="check")
        batch_op.create_check_constraint(
            "ck_oral_tasks_status",
            "status IN ('QUEUED', 'SUBMITTING', 'SUBMISSION_UNCERTAIN', 'RUNNING', "
            "'ARCHIVING', 'ARCHIVE_FAILED', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
        )
        batch_op.create_check_constraint("ck_oral_tasks_attempt_count", "attempt_count >= 0")
        batch_op.create_check_constraint(
            "ck_oral_tasks_billing_round",
            "billing_round IS NULL OR billing_round > 0",
        )
    op.create_index(
        "idx_oral_tasks_durable_claim",
        "oral_tasks",
        ["status", "next_attempt_at", "lease_expires_at", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    oral_rows = bind.execute(
        sa.text("SELECT COUNT(*) FROM wallet_transactions WHERE oral_task_id IS NOT NULL")
    ).scalar_one()
    if int(oral_rows) > 0:
        raise RuntimeError(
            "cannot downgrade 065 while oral wallet transactions exist; "
            "reconcile or export them first"
        )

    op.drop_index("idx_oral_tasks_durable_claim", table_name="oral_tasks")
    with op.batch_alter_table("oral_tasks") as batch_op:
        batch_op.drop_constraint("ck_oral_tasks_billing_round", type_="check")
        batch_op.drop_constraint("ck_oral_tasks_attempt_count", type_="check")
        batch_op.drop_constraint("ck_oral_tasks_status", type_="check")
        batch_op.create_check_constraint(
            "ck_oral_tasks_status",
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
        )
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_owner")
        batch_op.drop_column("provider_result_url")
        batch_op.drop_column("billing_round")

    op.drop_index("uq_wallet_transactions_oral_terminal_round", table_name="wallet_transactions")
    op.drop_index("uq_wallet_transactions_oral_reserve_round", table_name="wallet_transactions")
    with op.batch_alter_table("wallet_transactions") as batch_op:
        batch_op.drop_constraint("ck_wallet_transactions_shape", type_="check")
        batch_op.drop_constraint("fk_wallet_transactions_oral_task_id", type_="foreignkey")
        batch_op.drop_column("oral_task_id")
        batch_op.create_check_constraint("ck_wallet_transactions_shape", _WALLET_SHAPE_LEGACY)

    for table in ("oral_voices", "oral_avatars"):
        op.drop_index(f"idx_{table}_durable_claim", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"ck_{table}_attempt_count", type_="check")
            batch_op.drop_constraint(f"ck_{table}_submission_state", type_="check")
            batch_op.create_check_constraint(
                f"ck_{table}_submission_state",
                "submission_state IN ('LOCAL_PENDING', 'SUBMITTED', "
                "'SUBMISSION_UNKNOWN', 'FAILED')",
            )
            batch_op.drop_column("attempt_count")
            batch_op.drop_column("next_attempt_at")
            batch_op.drop_column("lease_expires_at")
            batch_op.drop_column("lease_owner")
