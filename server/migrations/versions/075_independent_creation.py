"""075_independent_creation — 独立视频创作通道（C2）.

generation_batches.project_id 改为可空：独立创作（文生/图生/参考生）
不属于任何项目，批次以 created_by_user_id 为归属。已有的复刻流批次
project_id 全部非空，语义不变。

runtime_settings.h3_extended_modes_enabled 是扩展模式（尾帧 / 文生 T2V /
参考生 R2V）真实提交的总开关：协议构造与测试先行落地，真实供应商提交
在按 docs/短视频复刻桌面端开发说明.md §21.3 完成供应商核对后才由管理端
打开。首帧图生（I2V）不受此开关影响。

Revision ID: 075_independent_creation
Revises: 074_script_rewrite_ip_profile_snapshot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "075_independent_creation"
down_revision = "074_script_rewrite_ip_profile_snapshot"
branch_labels = None
depends_on = None

_INDEPENDENT_LIST_INDEX = "idx_generation_batches_independent_list"


def upgrade() -> None:
    with op.batch_alter_table("generation_batches") as batch_op:
        batch_op.alter_column(
            "project_id",
            existing_type=sa.Text(),
            existing_nullable=False,
            nullable=True,
        )
    op.create_index(
        _INDEPENDENT_LIST_INDEX,
        "generation_batches",
        ["created_by_user_id", "created_at"],
        sqlite_where=sa.text("project_id IS NULL"),
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.add_column(
        "runtime_settings",
        sa.Column(
            "h3_extended_modes_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("runtime_settings", "h3_extended_modes_enabled")
    op.drop_index(_INDEPENDENT_LIST_INDEX, table_name="generation_batches")
    connection = op.get_bind()
    orphan_batches = connection.execute(
        sa.text("SELECT 1 FROM generation_batches WHERE project_id IS NULL LIMIT 1")
    ).fetchone()
    if orphan_batches is not None:
        raise RuntimeError(
            "cannot downgrade 075 while independent generation batches exist; "
            "export or delete them first"
        )
    with op.batch_alter_table("generation_batches") as batch_op:
        batch_op.alter_column(
            "project_id",
            existing_type=sa.Text(),
            existing_nullable=True,
            nullable=False,
        )
