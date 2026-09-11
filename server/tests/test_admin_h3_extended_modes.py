"""CW-063 — h3_extended_modes_enabled admin toggle route tests.

Dedicated PG database (cw063_h3_extended_modes_test) migrated to head,
mirroring ``test_admin_rate_routes``. Covers: default-off read, the shared
admin write contract (idempotency key / confirm / reason), auditor
read-only enforcement, idempotent replay, upsert on empty runtime_settings,
and the audit trail (setting='h3_extended_modes' + reason + request id).

The h3_extended_modes_enabled column gates real paid submissions of the
T2V / R2V / last_frame H3 forms (see docs/视频生成独立创作-设计与实施-2026-09-07.md
§五.1). The toggle defaults to FALSE (migration 075) and may only be flipped
after the supplier paid-probe verification (缺口 4a) completes; this suite
proves the control plane exists and is audited, not that the probe ran.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pg_test_kit import (
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    resolve_test_dsn,
)

from app.admin_auth_routes import (
    ADMIN_CSRF_HEADER,
    ADMIN_SESSION_HMAC_KEY_ENV,
    issue_exchange_credential,
)
from app.admin_write_contract import IDEMPOTENCY_KEY_HEADER
from app.db_pg import DATABASE_URL_ENV, close_pg_pool

TEST_KEY = "cw063-h3-test-hmac-key-0123456789abcdef"
CW063_DB_NAME = "cw063_h3_extended_modes_test"


@pytest.fixture(scope="module")
def h3_pg_dsn() -> Iterator[str]:
    """Dedicated migrated database with operator seed users."""
    from alembic import command
    from alembic.config import Config

    require_pg_or_explicit_skip(resolve_test_dsn())
    dsn = create_test_database(CW063_DB_NAME)
    server_dir = Path(__file__).resolve().parent.parent
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://"))
    command.upgrade(config, "head")
    with psycopg.connect(dsn, autocommit=True) as conn:
        for user_id, role in (("admin_u", "admin"), ("auditor_u", "auditor")):
            conn.execute(
                "INSERT INTO users (id, username, display_name, role) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (user_id, user_id, user_id.replace("_", " ").title(), role),
            )
    try:
        yield dsn
    finally:
        drop_test_database(CW063_DB_NAME)


@pytest.fixture()
def h3_app(monkeypatch: pytest.MonkeyPatch, h3_pg_dsn: str) -> Iterator[FastAPI]:
    from app.admin_auth_routes import router as admin_auth_router
    from app.admin_runtime_routes import router as admin_runtime_router

    app = FastAPI()
    app.include_router(admin_auth_router)
    app.include_router(admin_runtime_router)
    # CW-063: get_pg_pool() caches its DSN process-wide on first use, so reset
    # the singleton before repointing DATABASE_URL_ENV and again on teardown.
    # Without this the cw063 pool — whose database the module-scoped h3_pg_dsn
    # fixture drops at teardown — leaks into every later pool consumer in the
    # same shard process (seen as test_admin_rate_routes hitting a dropped
    # database). Matches the standalone-suite convention used by
    # test_wallet_billing_service / test_oral_domain / test_postgres_migrations.
    close_pg_pool()
    monkeypatch.setenv(DATABASE_URL_ENV, h3_pg_dsn)
    monkeypatch.setenv(ADMIN_SESSION_HMAC_KEY_ENV, TEST_KEY)
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    yield app
    close_pg_pool()


@pytest.fixture()
def client(h3_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(h3_app) as test_client:
        yield test_client


def _exchange(client: TestClient, actor: str = "admin_u") -> dict[str, str]:
    response = client.post(
        "/api/control/admin/session/exchange",
        json={"credential": issue_exchange_credential(actor, ttl_seconds=3600)},
    )
    assert response.status_code == 201, response.text
    return {ADMIN_CSRF_HEADER: response.json()["csrf_token"]}


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    return _exchange(client)


@pytest.fixture()
def auditor_headers(client: TestClient) -> dict[str, str]:
    return _exchange(client, "auditor_u")


def _write_headers(base: dict[str, str], *, key: str | None = None) -> dict[str, str]:
    headers = dict(base)
    headers[IDEMPOTENCY_KEY_HEADER] = key or f"key-{uuid.uuid4()}"
    return headers


def _seed_runtime_settings(dsn: str, *, h3_enabled: bool = False, fair_queue: bool = False) -> None:
    """Ensure runtime_settings row exists with given flags."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO runtime_settings (
                id, max_generation_count_per_batch, max_concurrent_h3_tasks,
                internal_base_unit_price_fen, min_recharge_fen, recharge_step_fen,
                active_storage_provider, fair_queue_enabled, h3_extended_modes_enabled,
                created_at, updated_at
            ) VALUES (1, 4, 100, 1000, 10000, 1000, 'cos', %s, %s,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                fair_queue_enabled = excluded.fair_queue_enabled,
                h3_extended_modes_enabled = excluded.h3_extended_modes_enabled,
                updated_at = CURRENT_TIMESTAMP
            """,
            (fair_queue, h3_enabled),
        )


def _read_h3_flag(dsn: str) -> bool:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT h3_extended_modes_enabled FROM runtime_settings WHERE id = 1"
        ).fetchone()
    return bool(row and row[0])


def _audit_rows(dsn: str, *, setting: str = "h3_extended_modes") -> list[dict]:
    """Read runtime_settings audit rows; metadata_json is TEXT, so parse it here.

    The audit_logs.metadata_json column is sa.Text() (migration 001), not
    jsonb, so the ``->>`` operator is unavailable — filter on the decoded
    payload in Python instead.
    """
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT actor_user_id, action, entity_type, entity_id, metadata_json
            FROM audit_logs
            WHERE action = 'runtime_settings.update'
            ORDER BY created_at
            """
        ).fetchall()
    matched: list[dict] = []
    for r in rows:
        meta = json.loads(r[4]) if isinstance(r[4], str) else dict(r[4] or {})
        if meta.get("setting") != setting:
            continue
        matched.append(
            {
                "actor_user_id": r[0],
                "action": r[1],
                "entity_type": r[2],
                "entity_id": r[3],
                "metadata_json": meta,
            }
        )
    return matched


def _clear_audit(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM audit_logs")


# --- Tests ---


def test_get_h3_extended_modes_requires_admin_session(client: TestClient) -> None:
    response = client.get("/api/control/settings/h3-extended-modes")
    assert response.status_code == 401


def test_get_h3_extended_modes_defaults_to_disabled(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=False)
    response = client.get("/api/control/settings/h3-extended-modes", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"h3_extended_modes_enabled": False}


def test_get_h3_extended_modes_reads_enabled(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=True)
    response = client.get("/api/control/settings/h3-extended-modes", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"h3_extended_modes_enabled": True}


def test_patch_h3_extended_modes_enables_with_write_contract(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=False)
    _clear_audit(h3_pg_dsn)
    key = f"key-{uuid.uuid4()}"
    response = client.patch(
        "/api/control/settings/h3-extended-modes",
        json={
            "h3_extended_modes_enabled": True,
            "confirm": True,
            "reason": "供应商付费探针核对通过，见 docs/evidence/H3-EXTENDED-MODES-PROBE.md",
        },
        headers=_write_headers(admin_headers, key=key),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"h3_extended_modes_enabled": True}
    assert _read_h3_flag(h3_pg_dsn) is True
    audits = _audit_rows(h3_pg_dsn)
    assert len(audits) == 1
    assert audits[0]["actor_user_id"] == "admin_u"
    assert audits[0]["action"] == "runtime_settings.update"
    assert audits[0]["entity_type"] == "runtime_settings"
    assert audits[0]["entity_id"] == "1"
    meta = audits[0]["metadata_json"]
    assert meta["h3_extended_modes_enabled"] is True
    assert meta["setting"] == "h3_extended_modes"
    assert "供应商付费探针" in meta["reason"]
    assert meta["request_id"]


def test_patch_h3_extended_modes_disables(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=True)
    _clear_audit(h3_pg_dsn)
    response = client.patch(
        "/api/control/settings/h3-extended-modes",
        json={
            "h3_extended_modes_enabled": False,
            "confirm": True,
            "reason": "回退：发现 metaso last_frame 不支持",
        },
        headers=_write_headers(admin_headers),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"h3_extended_modes_enabled": False}
    assert _read_h3_flag(h3_pg_dsn) is False


def test_patch_h3_extended_modes_rejects_auditor(
    client: TestClient, auditor_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=False)
    response = client.patch(
        "/api/control/settings/h3-extended-modes",
        json={
            "h3_extended_modes_enabled": True,
            "confirm": True,
            "reason": "auditor should not write",
        },
        headers=_write_headers(auditor_headers),
    )
    assert response.status_code == 403


def test_patch_h3_extended_modes_idempotent_replay(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=False)
    _clear_audit(h3_pg_dsn)
    key = f"key-{uuid.uuid4()}"
    payload = {
        "h3_extended_modes_enabled": True,
        "confirm": True,
        "reason": "幂等重放测试",
    }
    first = client.patch(
        "/api/control/settings/h3-extended-modes",
        json=payload,
        headers=_write_headers(admin_headers, key=key),
    )
    assert first.status_code == 200, first.text
    second = client.patch(
        "/api/control/settings/h3-extended-modes",
        json=payload,
        headers=_write_headers(admin_headers, key=key),
    )
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    audits = _audit_rows(h3_pg_dsn)
    assert len(audits) == 1, f"idempotent replay must not duplicate audit, got {len(audits)}"


def test_patch_h3_extended_modes_upserts_empty_settings_row(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    with psycopg.connect(h3_pg_dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM runtime_settings WHERE id = 1")
    _clear_audit(h3_pg_dsn)
    response = client.patch(
        "/api/control/settings/h3-extended-modes",
        json={
            "h3_extended_modes_enabled": True,
            "confirm": True,
            "reason": "upsert 兜底空表测试",
        },
        headers=_write_headers(admin_headers),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"h3_extended_modes_enabled": True}
    assert _read_h3_flag(h3_pg_dsn) is True


def test_patch_h3_extended_modes_requires_reason(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=False)
    response = client.patch(
        "/api/control/settings/h3-extended-modes",
        json={
            "h3_extended_modes_enabled": True,
            "confirm": True,
            "reason": "   ",
        },
        headers=_write_headers(admin_headers),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "REASON_REQUIRED"


def test_patch_h3_extended_modes_requires_confirm(
    client: TestClient, admin_headers: dict[str, str], h3_pg_dsn: str
) -> None:
    _seed_runtime_settings(h3_pg_dsn, h3_enabled=False)
    response = client.patch(
        "/api/control/settings/h3-extended-modes",
        json={
            "h3_extended_modes_enabled": True,
            "confirm": False,
            "reason": "confirm=false should reject",
        },
        headers=_write_headers(admin_headers),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
