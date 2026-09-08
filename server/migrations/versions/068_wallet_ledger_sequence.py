"""Preserve causal ordering for new wallet ledger entries.

Revision ID: 068_wallet_ledger_sequence
Revises: 067_activation_initial_free_seconds

Existing rows deliberately remain unsequenced: their second-resolution timestamps
cannot prove the order of concurrent-looking entries. New rows receive an immutable
database-assigned sequence so administrative balance snapshots can be reconstructed
without guessing from random transaction ids.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "068_wallet_ledger_sequence"
down_revision = "067_activation_initial_free_seconds"
branch_labels = None
depends_on = None

_SEQUENCE = "wallet_ledger_sequence_seq"
_INDEX = "uq_wallet_transactions_ledger_sequence"
_USER_INDEX = "idx_wallet_transactions_user_ledger_sequence"
_SQLITE_INSERT_GUARD = "trg_wallet_transactions_reject_explicit_ledger_sequence"
_SQLITE_UPDATE_GUARD = "trg_wallet_transactions_reject_ledger_sequence_update"
_SQLITE_INTERNAL_SEQUENCE = "ledger_sequence_internal"
_SQLITE_OLD_TABLE = "wallet_transactions_068_old"
_POSTGRES_TRIGGER = "trg_wallet_transactions_assign_ledger_sequence"
_POSTGRES_FUNCTION = "assign_wallet_ledger_sequence"

_WALLET_COLUMNS = (
    "id,user_id,type,available_delta,reserved_delta,recharge_order_id,task_id,"
    "billing_round,idempotency_key,created_at,oral_task_id"
)
_WALLET_SHAPE = (
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


def _sqlite_indexes(bind: sa.Connection) -> list[str]:
    return [
        str(row[0])
        for row in bind.execute(
            sa.text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name='wallet_transactions' AND sql IS NOT NULL ORDER BY name"
            )
        )
    ]


def _sqlite_create_wallet_transactions(*, historical_count: int | None) -> None:
    if historical_count is None:
        sequence_columns = ""
        id_constraint = "PRIMARY KEY (id),"
    else:
        sequence_columns = f"""
            {_SQLITE_INTERNAL_SEQUENCE} INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT
                CHECK ({_SQLITE_INTERNAL_SEQUENCE} > 0),
            ledger_sequence INTEGER GENERATED ALWAYS AS (
                CASE WHEN {_SQLITE_INTERNAL_SEQUENCE} > {historical_count}
                     THEN {_SQLITE_INTERNAL_SEQUENCE} - {historical_count}
                     ELSE NULL END
            ) STORED,
        """
        id_constraint = "UNIQUE (id),"
    op.execute(
        sa.text(
            f"""
            CREATE TABLE wallet_transactions (
                {sequence_columns}
                id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                type TEXT NOT NULL,
                available_delta INTEGER NOT NULL,
                reserved_delta INTEGER NOT NULL,
                recharge_order_id TEXT,
                task_id TEXT,
                billing_round INTEGER,
                idempotency_key TEXT NOT NULL,
                created_at TEXT DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                oral_task_id TEXT,
                {id_constraint}
                CONSTRAINT fk_wallet_transactions_oral_task_id FOREIGN KEY(oral_task_id) REFERENCES oral_tasks (id),
                CONSTRAINT ck_wallet_transactions_type
                    CHECK (type IN ('CHARGE', 'RESERVE', 'SETTLE', 'RELEASE')),
                CONSTRAINT ck_wallet_transactions_billing_round
                    CHECK (billing_round IS NULL OR billing_round > 0),
                CONSTRAINT ck_wallet_transactions_shape CHECK ({_WALLET_SHAPE}),
                UNIQUE (idempotency_key),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(task_id) REFERENCES generation_tasks(id),
                FOREIGN KEY(recharge_order_id) REFERENCES recharge_orders(id)
            )
            """
        )
    )


def _sqlite_rebuild_wallet_transactions(*, historical_count: int | None) -> None:
    bind = op.get_bind()
    indexes = _sqlite_indexes(bind)
    op.execute(sa.text(f"ALTER TABLE wallet_transactions RENAME TO {_SQLITE_OLD_TABLE}"))
    _sqlite_create_wallet_transactions(historical_count=historical_count)
    op.execute(
        sa.text(
            f"INSERT INTO wallet_transactions ({_WALLET_COLUMNS}) "
            f"SELECT {_WALLET_COLUMNS} FROM {_SQLITE_OLD_TABLE} ORDER BY rowid"
        )
    )
    op.execute(sa.text(f"DROP TABLE {_SQLITE_OLD_TABLE}"))
    for index_sql in indexes:
        op.execute(sa.text(index_sql))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        historical_count = int(
            bind.execute(sa.text("SELECT COUNT(*) FROM wallet_transactions")).scalar_one()
        )
        _sqlite_rebuild_wallet_transactions(historical_count=historical_count)
        op.create_index(
            _INDEX,
            "wallet_transactions",
            ["ledger_sequence"],
            unique=True,
            sqlite_where=sa.text("ledger_sequence IS NOT NULL"),
        )
        op.create_index(
            _USER_INDEX,
            "wallet_transactions",
            ["user_id", "ledger_sequence"],
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {_SQLITE_INSERT_GUARD}
                BEFORE INSERT ON wallet_transactions
                WHEN NEW.{_SQLITE_INTERNAL_SEQUENCE} != -1
                BEGIN
                    SELECT RAISE(ABORT, 'ledger_sequence is database assigned');
                END
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {_SQLITE_UPDATE_GUARD}
                BEFORE UPDATE OF {_SQLITE_INTERNAL_SEQUENCE} ON wallet_transactions
                WHEN NEW.{_SQLITE_INTERNAL_SEQUENCE} IS NOT OLD.{_SQLITE_INTERNAL_SEQUENCE}
                BEGIN
                    SELECT RAISE(ABORT, 'ledger_sequence is immutable');
                END
                """
            )
        )
        return

    op.add_column(
        "wallet_transactions",
        sa.Column("ledger_sequence", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        _INDEX,
        "wallet_transactions",
        ["ledger_sequence"],
        unique=True,
        sqlite_where=sa.text("ledger_sequence IS NOT NULL"),
        postgresql_where=sa.text("ledger_sequence IS NOT NULL"),
    )
    op.create_index(
        _USER_INDEX,
        "wallet_transactions",
        ["user_id", "ledger_sequence"],
    )

    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f"CREATE SEQUENCE {_SEQUENCE}"))
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {_POSTGRES_FUNCTION}()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF TG_OP = 'UPDATE' THEN
                        IF NEW.ledger_sequence IS DISTINCT FROM OLD.ledger_sequence THEN
                            RAISE EXCEPTION 'ledger_sequence is immutable';
                        END IF;
                        RETURN NEW;
                    END IF;
                    IF NEW.ledger_sequence IS NOT NULL THEN
                        RAISE EXCEPTION 'ledger_sequence is database assigned';
                    END IF;
                    PERFORM 1 FROM wallets
                    WHERE user_id = NEW.user_id
                    FOR UPDATE;
                    NEW.ledger_sequence := nextval('{_SEQUENCE}');
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {_POSTGRES_TRIGGER}
                BEFORE INSERT OR UPDATE ON wallet_transactions
                FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
                """
            )
        )
        return


def downgrade() -> None:
    bind = op.get_bind()
    sequenced = bind.execute(
        sa.text("SELECT 1 FROM wallet_transactions WHERE ledger_sequence IS NOT NULL LIMIT 1")
    ).first()
    if sequenced is not None:
        raise RuntimeError(
            "cannot downgrade 068 while wallet ledger sequences exist; preserve ordering evidence"
        )
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER {_POSTGRES_TRIGGER} ON wallet_transactions"))
        op.execute(sa.text(f"DROP FUNCTION {_POSTGRES_FUNCTION}()"))
        op.execute(sa.text(f"DROP SEQUENCE {_SEQUENCE}"))
    elif bind.dialect.name == "sqlite":
        op.execute(sa.text(f"DROP TRIGGER {_SQLITE_UPDATE_GUARD}"))
        op.execute(sa.text(f"DROP TRIGGER {_SQLITE_INSERT_GUARD}"))
        op.drop_index(_USER_INDEX, table_name="wallet_transactions")
        op.drop_index(_INDEX, table_name="wallet_transactions")
        _sqlite_rebuild_wallet_transactions(historical_count=None)
        return

    op.drop_index(_USER_INDEX, table_name="wallet_transactions")
    op.drop_index(_INDEX, table_name="wallet_transactions")
    op.drop_column("wallet_transactions", "ledger_sequence")
