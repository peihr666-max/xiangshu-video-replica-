"""077_oral_unit_price — make the per-render oral price configurable.

Revision ID: 077_oral_unit_price
Revises: 076_studio_notification_preferences
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "077_oral_unit_price"
down_revision = "076_studio_notification_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "oral_unit_price_fen",
                sa.Integer(),
                nullable=False,
                server_default="1000",
            )
        )
        batch_op.create_check_constraint(
            "ck_runtime_settings_oral_unit_price_positive",
            "oral_unit_price_fen > 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.drop_constraint(
            "ck_runtime_settings_oral_unit_price_positive",
            type_="check",
        )
        batch_op.drop_column("oral_unit_price_fen")
