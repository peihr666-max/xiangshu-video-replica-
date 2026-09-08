"""Allow explicitly authorized initial free seconds without booking revenue.

Revision ID: 067_activation_initial_free_seconds
Revises: 066_operation_cost_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "067_activation_initial_free_seconds"
down_revision = "066_operation_cost_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint(
        "ck_activation_code_batches_license_credit_shape", "activation_code_batches", type_="check"
    )
    op.create_check_constraint(
        "ck_activation_code_batches_license_credit_shape",
        "activation_code_batches",
        "face_value_fen = 0 OR credits_snapshot > 0",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM activation_code_batches "
            "WHERE face_value_fen = 0 AND credits_snapshot > 0)"
        )
    ).scalar():
        raise RuntimeError(
            "Cannot downgrade 067 while initial free-second batches exist; "
            "preserve their authorization and ledger history."
        )
    op.drop_constraint(
        "ck_activation_code_batches_license_credit_shape", "activation_code_batches", type_="check"
    )
    op.create_check_constraint(
        "ck_activation_code_batches_license_credit_shape",
        "activation_code_batches",
        "(face_value_fen = 0 AND credits_snapshot = 0) "
        "OR (face_value_fen > 0 AND credits_snapshot > 0)",
    )
