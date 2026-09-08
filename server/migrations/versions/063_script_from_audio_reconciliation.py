"""Preserve provider submission identity for uncertain reconciliation.

Revision ID: 063_script_from_audio_reconciliation
Revises: 062_viral_video_library
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "063_script_from_audio_reconciliation"
down_revision = "062_viral_video_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oral_tasks", sa.Column("provider_started_at", sa.Text()))
    op.add_column("script_from_audio_tasks", sa.Column("provider_task_id", sa.Text()))


def downgrade() -> None:
    bind = op.get_bind()
    script_task = bind.execute(
        sa.text("SELECT 1 FROM script_from_audio_tasks WHERE provider_task_id IS NOT NULL LIMIT 1")
    ).first()
    oral_task = bind.execute(
        sa.text("SELECT 1 FROM oral_tasks WHERE provider_started_at IS NOT NULL LIMIT 1")
    ).first()
    if script_task or oral_task:
        raise RuntimeError(
            "cannot downgrade 063 while provider reconciliation data exists; "
            "reconcile active submissions first"
        )
    with op.batch_alter_table("script_from_audio_tasks") as batch_op:
        batch_op.drop_column("provider_task_id")
    with op.batch_alter_table("oral_tasks") as batch_op:
        batch_op.drop_column("provider_started_at")
