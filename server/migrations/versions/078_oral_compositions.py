"""078_oral_compositions — durable, non-billable oral post-production jobs.

Revision ID: 078_oral_compositions
Revises: 077_oral_unit_price
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "078_oral_compositions"
down_revision = "077_oral_unit_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oral_compositions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column(
            "oral_task_id",
            sa.Text(),
            sa.ForeignKey("oral_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_asset_id",
            sa.Text(),
            sa.ForeignKey("assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="QUEUED"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("retry_of_id", sa.Text(), sa.ForeignKey("oral_compositions.id")),
        sa.Column("result_asset_id", sa.Text(), sa.ForeignKey("assets.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("locked_by", sa.Text()),
        sa.Column("lease_token", sa.Text()),
        sa.Column("locked_until", sa.Text()),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_oral_compositions_owner_idempotency"
        ),
        sa.UniqueConstraint("oral_task_id", "version", name="uq_oral_compositions_version"),
        sa.CheckConstraint(
            "template IN ('bottom_caption', 'center_banner', 'top_title')",
            name="ck_oral_compositions_template",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_oral_compositions_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_oral_compositions_version_positive"),
        sa.CheckConstraint("attempt >= 0", name="ck_oral_compositions_attempt_nonnegative"),
        sa.CheckConstraint("is_active IN (0, 1)", name="ck_oral_compositions_active"),
    )
    op.create_index("idx_oral_compositions_queue", "oral_compositions", ["status", "created_at"])
    op.create_index(
        "idx_oral_compositions_owner", "oral_compositions", ["owner_user_id", "created_at"]
    )
    op.create_index(
        "uq_oral_compositions_active_task",
        "oral_compositions",
        ["oral_task_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_oral_compositions_active_task", table_name="oral_compositions")
    op.drop_index("idx_oral_compositions_owner", table_name="oral_compositions")
    op.drop_index("idx_oral_compositions_queue", table_name="oral_compositions")
    op.drop_table("oral_compositions")
