from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "067_oral_unit_price"
down_revision = "066_script_rewrite_ip_profile_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_settings",
        sa.Column(
            "oral_unit_price_fen",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
    )


def downgrade() -> None:
    op.drop_column("runtime_settings", "oral_unit_price_fen")
