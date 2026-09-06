"""076_publish_module — C5 发布能力：平台发布账号与发布记录.

publish_accounts 保存用户在抖音/视频号的创作者登录态：Cookie 与抖音
security_sdk 材料以 Fernet 密文落库（VIDEO_REPLICA_SETTINGS_KEY 体系），
任何 API 响应都不回传凭据明文。verify_requested 驱动 publish_worker 的
异步登录态探测，失效账号标记 invalid 并要求重新连接。

publish_records 承载发布草稿与发布任务：draft → queued → publishing →
published / failed / canceled。cover_asset_id 指向素材库 image 资产
（assets.kind 含 image），asset_id 指向成片资产（assets.kind 含 video）。
schedule_at 存 UTC "YYYY-MM-DD HH:MM:SS" 文本，与 CURRENT_TIMESTAMP 的
字符串比较语义一致，worker 直接用它做定时判断。同一账号同时只允许一个
publishing 记录（由 claim 查询的 NOT EXISTS 保证）。

Revision ID: 076_publish_module
Revises: 075_independent_creation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "076_publish_module"
down_revision = "075_independent_creation"
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


def _lease_columns() -> list[sa.Column[str | int]]:
    return [
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    ]


def upgrade() -> None:
    op.create_table(
        "publish_accounts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("cookie_enc", sa.Text(), nullable=False),
        sa.Column("security_sdk_enc", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="connected"),
        sa.Column("verify_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_verified_at", sa.Text()),
        sa.Column("error_message", sa.Text()),
        *_lease_columns(),
        *_timestamps(),
        sa.CheckConstraint(
            "platform IN ('douyin', 'wechat_channels')",
            name="ck_publish_accounts_platform",
        ),
        sa.CheckConstraint(
            "status IN ('connected', 'invalid')", name="ck_publish_accounts_status"
        ),
        sa.CheckConstraint(
            "verify_requested IN (0, 1)", name="ck_publish_accounts_verify_flag"
        ),
    )
    op.create_index(
        "idx_publish_accounts_user_created",
        "publish_accounts",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "idx_publish_accounts_verify_queue",
        "publish_accounts",
        ["verify_requested", "lease_expires_at"],
    )

    op.create_table(
        "publish_records",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column(
            "account_id",
            sa.Text(),
            sa.ForeignKey("publish_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("cover_asset_id", sa.Text()),
        sa.Column("schedule_at", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("platform_item_id", sa.Text()),
        sa.Column("short_url", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("published_at", sa.Text()),
        *_lease_columns(),
        *_timestamps(),
        sa.CheckConstraint(
            "platform IN ('douyin', 'wechat_channels')",
            name="ck_publish_records_platform",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'queued', 'publishing', 'published', 'failed',"
            " 'canceled')",
            name="ck_publish_records_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_publish_records_attempts"),
    )
    op.create_index(
        "idx_publish_records_user_created",
        "publish_records",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "idx_publish_records_queue",
        "publish_records",
        ["status", "schedule_at"],
    )
    op.create_index(
        "idx_publish_records_account_active",
        "publish_records",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("publish_records")
    op.drop_table("publish_accounts")
