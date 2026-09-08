"""Append-only cost and second-based billing migration coverage."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

DEFAULT_DSN = "postgresql://testuser:testpass@localhost:5433/customer_v3_test"
DB_NAME = "cost_billing_migrations_test"


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
def migration_dsn() -> Iterator[str]:
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


@pytest.mark.pg
def test_operation_cost_rates_upgrade_from_063_and_downgrade(migration_dsn: str) -> None:
    config = _config(migration_dsn)
    command.upgrade(config, "063_script_from_audio_reconciliation")
    with psycopg.connect(migration_dsn) as conn:
        assert conn.execute("SELECT to_regclass('operation_cost_rates')").fetchone() == (None,)

    command.upgrade(config, "064_operation_cost_rates")
    with psycopg.connect(migration_dsn) as conn:
        rows = conn.execute(
            "SELECT subject, kind, unit, unit_price_fen FROM operation_cost_rates ORDER BY subject"
        ).fetchall()
        assert len(rows) == 9
        assert ("video_generation_768p", "upstream_cost", "second", 9) in rows
        assert ("external_price_2k", "external_price", "second", 20) in rows

    command.downgrade(config, "063_script_from_audio_reconciliation")
    with psycopg.connect(migration_dsn) as conn:
        assert conn.execute("SELECT to_regclass('operation_cost_rates')").fetchone() == (None,)


@pytest.mark.pg
def test_second_based_billing_preserves_oral_shape_and_guards_downgrade(
    migration_dsn: str,
) -> None:
    config = _config(migration_dsn)
    command.upgrade(config, "065_second_based_billing")
    with psycopg.connect(migration_dsn) as conn:
        foreign_keys = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='wallet_transactions'::regclass AND contype='f'"
        ).fetchall()
        assert any("oral_task_id" in str(row[0]) for row in foreign_keys)
        indexes = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename='wallet_transactions'"
        ).fetchall()
        assert any(
            "oral_task_id" in str(row[0]) and "billing_round" in str(row[0]) for row in indexes
        )
        conn.execute(
            "INSERT INTO users (id,username,display_name) "
            "VALUES ('seconds-user','seconds-user','Seconds User')"
        )
        conn.execute(
            "INSERT INTO projects (id,owner_user_id,name) "
            "VALUES ('seconds-project','seconds-user','Seconds Project')"
        )
        conn.execute(
            "INSERT INTO generation_batches "
            "(id,project_id,created_by_user_id,idempotency_key,request_hash,request_snapshot_json) "
            "VALUES ('seconds-batch','seconds-project','seconds-user','seconds-key','hash','{}')"
        )
        conn.execute(
            "INSERT INTO generation_tasks "
            "(id,batch_id,generation_mode,provider,model,status,billed_seconds) "
            "VALUES ('seconds-task','seconds-batch','I2V','fake_h3','MiniMax-H3','PENDING',15)"
        )
        conn.execute(
            "INSERT INTO person_identities (id,owner_user_id,display_name) "
            "VALUES ('seconds-identity','seconds-user','Identity')"
        )
        conn.execute(
            "INSERT INTO oral_avatars "
            "(id,identity_id,owner_user_id,title,status,source_kind,source_asset_id) "
            "VALUES ('seconds-avatar','seconds-identity','seconds-user','Avatar',"
            "'READY','VIDEO','asset')"
        )
        conn.execute(
            "INSERT INTO oral_tasks "
            "(id,owner_user_id,project_id,identity_id,avatar_id,mode,title,status,"
            "estimated_cost_fen,idempotency_key) VALUES "
            "('seconds-oral','seconds-user','seconds-project','seconds-identity',"
            "'seconds-avatar','AUDIO','Oral','QUEUED',1000,'seconds-oral-key')"
        )
        conn.execute(
            "INSERT INTO wallets (user_id,available_credits,reserved_credits) "
            "VALUES ('seconds-user',5,16)"
        )
        conn.execute(
            "INSERT INTO wallet_transactions "
            "(id,user_id,type,available_delta,reserved_delta,task_id,billing_round,"
            "idempotency_key) VALUES "
            "('seconds-reserve','seconds-user','RESERVE',-15,15,'seconds-task',1,"
            "'seconds-reserve')"
        )
        conn.execute(
            "INSERT INTO wallet_transactions "
            "(id,user_id,type,available_delta,reserved_delta,oral_task_id,billing_round,"
            "idempotency_key) VALUES "
            "('oral-reserve','seconds-user','RESERVE',-1,1,'seconds-oral',1,'oral-reserve')"
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="cannot downgrade 065"):
        command.downgrade(config, "064_operation_cost_rates")
    with psycopg.connect(migration_dsn) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "065_second_based_billing",
        )
        conn.execute("DELETE FROM wallet_transactions WHERE id='seconds-reserve'")
        conn.execute("UPDATE generation_tasks SET billed_seconds=NULL WHERE id='seconds-task'")
        conn.commit()

    command.downgrade(config, "064_operation_cost_rates")
    with psycopg.connect(migration_dsn) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='generation_tasks' AND column_name='billed_seconds'"
            ).fetchone()
            is None
        )
        assert conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='wallet_transactions' AND column_name='oral_task_id'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT type,reserved_delta FROM wallet_transactions WHERE id='oral-reserve'"
        ).fetchone() == ("RESERVE", 1)


@pytest.mark.pg
@pytest.mark.parametrize(
    "starting_revision",
    [None, "062_viral_video_library", "063_script_from_audio_reconciliation"],
)
def test_cost_billing_chain_reaches_head_from_supported_start(
    migration_dsn: str,
    starting_revision: str | None,
) -> None:
    config = _config(migration_dsn)
    if starting_revision is not None:
        command.upgrade(config, starting_revision)
    command.upgrade(config, "head")
    with psycopg.connect(migration_dsn) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "068_wallet_ledger_sequence",
        )
        assert conn.execute("SELECT to_regclass('operation_cost_rates')").fetchone()[0]
        assert conn.execute("SELECT to_regclass('operation_cost_records')").fetchone()[0]
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='generation_tasks'"
            ).fetchall()
        }
        assert {"billed_seconds", "actual_output_seconds", "cost_status"} <= columns

    if starting_revision is not None:
        command.downgrade(config, starting_revision)
        command.upgrade(config, "head")
