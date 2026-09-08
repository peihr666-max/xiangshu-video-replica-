"""C1 数字人口播领域：分身 / 声音 / 口播任务。

Vendor-neutral naming on purpose: tables never mention the upstream vendor;
vendor ids are opaque strings. Wallet billing for oral tasks deliberately
waits for a dedicated slice — the internal-billing reconciler (BILL-03) is
generation-task scoped, so wiring RESERVE/SETTLE here without a task-type
discriminator would let it auto-release oral reservations.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "057_oral_domain"
down_revision = "056_hifly_provider"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column[str]]:
    return [
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "oral_avatars",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "identity_id",
            sa.Text(),
            sa.ForeignKey("person_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("vendor_avatar_id", sa.Text()),
        sa.Column("vendor_task_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_asset_id", sa.Text(), nullable=False),
        sa.Column("consent_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("request_hash", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("locked_by", sa.Text()),
        sa.Column("lease_token", sa.Text()),
        sa.Column("locked_until", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUBMITTING', 'SUBMISSION_UNCERTAIN', "
            "'RUNNING', 'READY', 'FAILED')",
            name="ck_oral_avatars_status",
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_oral_avatars_owner_idempotency_key",
        ),
        sa.CheckConstraint(
            "source_kind IN ('VIDEO', 'IMAGE')",
            name="ck_oral_avatars_source_kind",
        ),
    )
    op.create_index(
        "idx_oral_avatars_identity",
        "oral_avatars",
        ["identity_id", "status"],
    )

    op.create_table(
        "oral_voices",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "identity_id",
            sa.Text(),
            sa.ForeignKey("person_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("vendor_voice_id", sa.Text()),
        sa.Column("vendor_task_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("source_asset_id", sa.Text(), nullable=False),
        sa.Column("consent_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("request_hash", sa.Text()),
        sa.Column("demo_asset_id", sa.Text()),
        sa.Column("confirmed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("locked_by", sa.Text()),
        sa.Column("lease_token", sa.Text()),
        sa.Column("locked_until", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUBMITTING', 'SUBMISSION_UNCERTAIN', "
            "'RUNNING', 'READY', 'FAILED')",
            name="ck_oral_voices_status",
        ),
        sa.CheckConstraint("confirmed IN (0, 1)", name="ck_oral_voices_confirmed"),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_oral_voices_owner_idempotency_key",
        ),
    )
    op.create_index(
        "idx_oral_voices_identity",
        "oral_voices",
        ["identity_id", "status"],
    )

    op.create_table(
        "oral_tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.Text(),
            sa.ForeignKey("person_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "avatar_id",
            sa.Text(),
            sa.ForeignKey("oral_avatars.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "voice_id",
            sa.Text(),
            sa.ForeignKey("oral_voices.id", ondelete="RESTRICT"),
        ),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("script_text", sa.Text()),
        sa.Column("audio_asset_id", sa.Text()),
        sa.Column("subtitle_json", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="QUEUED"),
        sa.Column("vendor_task_id", sa.Text()),
        sa.Column("result_asset_id", sa.Text()),
        sa.Column("duration_sec", sa.Integer()),
        sa.Column("estimated_cost_fen", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("vendor_error_code", sa.Integer()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_by", sa.Text()),
        sa.Column("lease_token", sa.Text()),
        sa.Column("locked_until", sa.Text()),
        sa.Column("next_poll_at", sa.Text()),
        sa.Column("submitted_at", sa.Text()),
        sa.Column("completed_at", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_oral_tasks_owner_idempotency_key",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'SUBMITTING', 'RUNNING', 'SUBMISSION_UNCERTAIN', "
            "'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_oral_tasks_status",
        ),
        sa.CheckConstraint("mode IN ('TTS', 'AUDIO')", name="ck_oral_tasks_mode"),
    )
    op.create_index(
        "idx_oral_tasks_owner",
        "oral_tasks",
        ["owner_user_id", "created_at"],
    )
    with op.batch_alter_table("wallet_transactions") as batch_op:
        batch_op.add_column(sa.Column("oral_task_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_wallet_transactions_oral_task_id",
            "oral_tasks",
            ["oral_task_id"],
            ["id"],
        )
        batch_op.drop_constraint("ck_wallet_transactions_shape", type_="check")
        batch_op.create_check_constraint(
            "ck_wallet_transactions_shape",
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
            "AND billing_round IS NOT NULL)",
        )
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


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT 1 FROM wallet_transactions WHERE oral_task_id IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError(
            "cannot downgrade 057 while oral wallet transactions exist; "
            "reconcile and export oral billing history first"
        )
    op.drop_index("uq_wallet_transactions_oral_terminal_round", table_name="wallet_transactions")
    op.drop_index("uq_wallet_transactions_oral_reserve_round", table_name="wallet_transactions")
    with op.batch_alter_table("wallet_transactions") as batch_op:
        batch_op.drop_constraint("ck_wallet_transactions_shape", type_="check")
        batch_op.drop_constraint("fk_wallet_transactions_oral_task_id", type_="foreignkey")
        batch_op.drop_column("oral_task_id")
        batch_op.create_check_constraint(
            "ck_wallet_transactions_shape",
            "(type = 'CHARGE' AND available_delta > 0 AND reserved_delta = 0 "
            "AND recharge_order_id IS NOT NULL AND task_id IS NULL AND billing_round IS NULL) OR "
            "(type = 'RESERVE' AND available_delta = -1 AND reserved_delta = 1 "
            "AND recharge_order_id IS NULL AND task_id IS NOT NULL "
            "AND billing_round IS NOT NULL) OR "
            "(type = 'SETTLE' AND available_delta = 0 AND reserved_delta = -1 "
            "AND recharge_order_id IS NULL AND task_id IS NOT NULL "
            "AND billing_round IS NOT NULL) OR "
            "(type = 'RELEASE' AND available_delta = 1 AND reserved_delta = -1 "
            "AND recharge_order_id IS NULL AND task_id IS NOT NULL AND billing_round IS NOT NULL)",
        )
    op.drop_table("oral_tasks")
    op.drop_table("oral_voices")
    op.drop_table("oral_avatars")
