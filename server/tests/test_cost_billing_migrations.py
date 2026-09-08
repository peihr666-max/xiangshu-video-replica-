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
