"""CW-042-a: the SQLite lane entry points fail closed in customer production.

042-a (owner-signed split per ``docs/evidence/CW042-SCOPE-INVENTORY.md`` §2.4)
tightens the internal/desktop SQLite fallback ENTRIES without deleting the
implementation — ``app/db.py`` stays, ``SQLiteBackend`` stays, and 042-b keeps
its CW-039 constraint (physical deletion only after the rollback manual is
frozen and the rehearsal environment exists).

``app/db.py`` is the single in-process choke point every runtime SQLite entry
goes through (``connect_database`` / ``initialize_database`` /
``upgrade_database``), so customer production refuses there with a fixed,
credential-free message. The HTTP surface is already covered by the CW-025
lifespan guard (internal lane rejected in customer production); this closes
the process-level entries that never run a lifespan: the internal-accounts
CLI (CW-041 surface), the historical backup tool (CW-040 surface) and the
desktop bootstrap helpers.

The internal/desktop lane itself (dev, test, CI, desktop) does not set
``VIDEO_REPLICA_CUSTOMER_PRODUCTION`` and keeps working — pinned here by the
negative cases and in CW-056's internal-lane migration regression lock.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import connect_database, initialize_database, upgrade_database

CUSTOMER_PRODUCTION_ENV = "VIDEO_REPLICA_CUSTOMER_PRODUCTION"
_REFUSAL_SNIPPET = "customer production is PostgreSQL-only"


@pytest.fixture()
def customer_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CUSTOMER_PRODUCTION_ENV, "true")


def test_connect_database_refuses_in_customer_production(
    customer_production: None, tmp_path: Path
) -> None:
    target = tmp_path / "prod.db"
    with pytest.raises(RuntimeError, match=_REFUSAL_SNIPPET):
        connect_database(target)
    # Fail closed BEFORE any filesystem side effect: no database file, no WAL.
    assert not target.exists()


def test_initialize_database_refuses_in_customer_production(
    customer_production: None, tmp_path: Path
) -> None:
    target = tmp_path / "prod.db"
    with pytest.raises(RuntimeError, match=_REFUSAL_SNIPPET):
        initialize_database(target)
    assert not target.exists()


def test_upgrade_database_refuses_in_customer_production(
    customer_production: None, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match=_REFUSAL_SNIPPET):
        upgrade_database(tmp_path / "prod.db")


@pytest.mark.parametrize("value", ["1", "TRUE", "Yes", "on", " true "])
def test_truthy_production_values_refuse(
    monkeypatch: pytest.MonkeyPatch, value: str, tmp_path: Path
) -> None:
    monkeypatch.setenv(CUSTOMER_PRODUCTION_ENV, value)
    with pytest.raises(RuntimeError, match=_REFUSAL_SNIPPET):
        connect_database(tmp_path / "prod.db")


@pytest.mark.parametrize("value", ["0", "false", "", "production-off"])
def test_non_production_values_keep_the_internal_lane_open(
    monkeypatch: pytest.MonkeyPatch, value: str, tmp_path: Path
) -> None:
    monkeypatch.setenv(CUSTOMER_PRODUCTION_ENV, value)
    conn = connect_database(tmp_path / "internal.db")
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_unset_env_keeps_desktop_lane_open(tmp_path: Path) -> None:
    conn = initialize_database(tmp_path / "desktop.db")
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "users" in tables
    finally:
        conn.close()


def test_refusal_message_is_fixed_and_credential_free(
    customer_production: None, tmp_path: Path
) -> None:
    secret = "postgresql://op:hunter2@db.internal:5432/prod"
    with pytest.raises(RuntimeError) as excinfo:
        connect_database(tmp_path / "prod.db")
    message = str(excinfo.value)
    assert message == (
        "customer production is PostgreSQL-only: the SQLite lane "
        "(VIDEO_REPLICA_DB_PATH / app.db entry points) is not available here; "
        "configure VIDEO_REPLICA_DATABASE_URL instead"
    )
    assert secret not in message
