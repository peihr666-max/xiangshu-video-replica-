from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

DEFAULT_DSN = "postgresql://testuser:testpass@localhost:5433/customer_v3_test"
DB_NAME = "wallet_ledger_sequence_test"


def _dsn() -> str:
    return os.environ.get("TEST_POSTGRESQL_URL", DEFAULT_DSN)


def _database_dsn(name: str) -> str:
    return _dsn().rsplit("/", 1)[0] + f"/{name}"


def _config(dsn: str) -> Config:
    server_dir = Path(__file__).resolve().parent.parent
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://"))
    return config


@pytest.fixture()
def ledger_dsn() -> Iterator[str]:
    try:
        with psycopg.connect(_dsn(), connect_timeout=3):
            pass
    except Exception:
        pytest.skip("PostgreSQL fixture is not available")
    admin_dsn = _database_dsn("postgres")
    target_dsn = _database_dsn(DB_NAME)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    try:
        yield target_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


def _seed_order(conn: psycopg.Connection, suffix: str) -> None:
    conn.execute(
        "INSERT INTO recharge_orders "
        "(id,user_id,merchant_order_no,provider,status,pricing_scope,"
        "base_unit_price_fen_snapshot,charged_unit_price_fen_snapshot,"
        "min_recharge_fen_snapshot,recharge_step_fen_snapshot,amount_fen,credits,paid_at) "
        "VALUES (%s,'ledger-user',%s,'zpay','PAID','INTERNAL',1000,1000,1,1,1000,10,now())",
        (f"ledger-order-{suffix}", f"ledger-merchant-{suffix}"),
    )


def _insert_charge(conn: psycopg.Connection, suffix: str) -> int:
    return int(
        conn.execute(
            "INSERT INTO wallet_transactions "
            "(id,user_id,type,available_delta,reserved_delta,recharge_order_id,idempotency_key) "
            "VALUES (%s,'ledger-user','CHARGE',10,0,%s,%s) RETURNING ledger_sequence",
            (f"ledger-tx-{suffix}", f"ledger-order-{suffix}", f"ledger-key-{suffix}"),
        ).fetchone()[0]
    )


@pytest.mark.pg
def test_wallet_sequence_serializes_same_wallet_and_downgrades_safely(ledger_dsn: str) -> None:
    config = _config(ledger_dsn)
    command.upgrade(config, "067_activation_initial_free_seconds")
    with psycopg.connect(ledger_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO users (id,username,display_name) "
            "VALUES ('ledger-user','ledger-user','Ledger User')"
        )
        conn.execute("INSERT INTO wallets (user_id) VALUES ('ledger-user')")
        _seed_order(conn, "historical")
        conn.execute(
            "INSERT INTO wallet_transactions "
            "(id,user_id,type,available_delta,reserved_delta,recharge_order_id,idempotency_key) "
            "VALUES ('ledger-tx-historical','ledger-user','CHARGE',10,0,"
            "'ledger-order-historical','ledger-key-historical')"
        )
        _seed_order(conn, "one")
        _seed_order(conn, "two")

    command.upgrade(config, "068_wallet_ledger_sequence")
    with psycopg.connect(ledger_dsn) as conn:
        assert conn.execute(
            "SELECT ledger_sequence FROM wallet_transactions WHERE id='ledger-tx-historical'"
        ).fetchone() == (None,)

    barrier = threading.Barrier(2)
    sequences: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def insert(suffix: str) -> None:
        try:
            with psycopg.connect(ledger_dsn, autocommit=True) as conn:
                barrier.wait()
                sequence = _insert_charge(conn, suffix)
            with lock:
                sequences.append(sequence)
        except BaseException as exc:  # pragma: no cover - assertion reports exact failure
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=insert, args=(suffix,)) for suffix in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(set(sequences)) == 2

    with psycopg.connect(ledger_dsn, autocommit=True) as conn:
        sequence = conn.execute(
            "SELECT ledger_sequence FROM wallet_transactions WHERE id='ledger-tx-one'"
        ).fetchone()[0]
        with pytest.raises(psycopg.Error, match="database assigned"):
            conn.execute(
                "INSERT INTO wallet_transactions "
                "(id,user_id,type,available_delta,reserved_delta,recharge_order_id,"
                "idempotency_key,ledger_sequence) VALUES "
                "('ledger-explicit','ledger-user','CHARGE',10,0,'ledger-order-one',"
                "'ledger-explicit',999)"
            )
        with pytest.raises(psycopg.Error, match="immutable"):
            conn.execute(
                "UPDATE wallet_transactions SET ledger_sequence=%s WHERE id='ledger-tx-one'",
                (int(sequence) + 1,),
            )

    command.downgrade(config, "067_activation_initial_free_seconds")
    with psycopg.connect(ledger_dsn) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='wallet_transactions' AND column_name='ledger_sequence'"
            ).fetchone()
            is None
        )
        assert conn.execute("SELECT count(*) FROM wallet_transactions").fetchone()[0] == 3
