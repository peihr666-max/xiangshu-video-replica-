"""CW-076 — customer self-service registration.

Fail-first tests for the frozen files ``server/app/password_hashing.py`` and
``server/app/customer_auth_routes.py`` plus the registration revision. Three lanes:

- password-hashing units and the fail-closed 503 guard run with NO database, so
  they execute in every environment (including a laptop without PostgreSQL);
- the ``POST /api/customer/register`` contract runs against a dedicated migrated
  PostgreSQL fixture database: the account (``role='customer'`` + a salted
  scrypt hash + ``registration_source='self_register'``) and its wallet are
  created atomically, the secret never leaves the boundary, and the stable
  error codes (409 ``USERNAME_TAKEN`` / 400 ``WEAK_PASSWORD`` / 400
  ``INVALID_USERNAME``) own their cases instead of a 422 or a 500;
- the registration revision's schema guards run against their OWN dedicated database so the
  downgrade rehearsal can never disturb the route fixture: the three CHECK
  constraints reject a password-less ``self_register``, a blank hash and an
  unknown source, and the downgrade refuses (then symmetrically succeeds) per
  the 026/044/083 data-loss-guard precedent.

The route fixture database is self-managed with raw admin DROP/CREATE (the
``test_customer_devices`` precedent), so no name is added to
``pg_test_kit.RECORDED_TEST_DATABASES`` — that allowlist only guards the kit's
own ``create_test_database`` helper.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pg_test_kit import require_pg_or_explicit_skip
from psycopg.errors import CheckViolation

from app.db_pg import DATABASE_URL_ENV, close_pg_pool
from app.password_hashing import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)

DEFAULT_DSN = "postgresql://testuser:testpass@localhost:5433/customer_v3_test"

# Two dedicated databases, each created/dropped by its own module fixture so the
# downgrade rehearsal never shares a database with the route contract tests.
CW076_DB_NAME = "cw076_registration_test"
CW076_MIGRATION_DB_NAME = "cw076_migration_test"

REGISTER_PATH = "/api/customer/register"
HEAD_REVISION = "20260912T1400_customer_registration_credentials"
PRIOR_REVISION = "20260912T1353_customer_discounts"

# A policy-valid password (>= MIN_PASSWORD_LENGTH, not blank). Never a secret.
VALID_PASSWORD = "correct-horse-battery"


def _pg_dsn() -> str:
    return os.environ.get("TEST_POSTGRESQL_URL", DEFAULT_DSN)


def _admin_dsn() -> str:
    return _pg_dsn().rsplit("/", 1)[0] + "/postgres"


def _dedicated_dsn(database: str) -> str:
    return _pg_dsn().rsplit("/", 1)[0] + f"/{database}"


def _alembic_config(dsn: str) -> Any:
    """In-process Alembic config (mirrors test_customer_devices / cw056)."""
    from alembic.config import Config

    server_dir = Path(__file__).resolve().parent.parent
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://"))
    return config


# ---------------------------------------------------------------------------
# Lane 1 — password hashing units (no database) — always run
# ---------------------------------------------------------------------------


def test_hash_password_is_scrypt_encoded_and_hides_plaintext() -> None:
    encoded = hash_password(VALID_PASSWORD)
    assert encoded.startswith("scrypt$")
    assert len(encoded.split("$")) == 6
    assert VALID_PASSWORD not in encoded


def test_hash_password_is_salted_so_repeats_diverge() -> None:
    first = hash_password(VALID_PASSWORD)
    second = hash_password(VALID_PASSWORD)
    assert first != second, "a fresh salt must make two hashes of one password differ"
    assert verify_password(VALID_PASSWORD, first)
    assert verify_password(VALID_PASSWORD, second)


def test_verify_password_rejects_a_wrong_password() -> None:
    encoded = hash_password(VALID_PASSWORD)
    assert verify_password(VALID_PASSWORD + "!", encoded) is False


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "scrypt",
        "scrypt$16384$8$1$AAAA",  # too few fields
        "pbkdf2$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA$BBBB",  # wrong algorithm
        "scrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA$BBBB",  # wrong cost params
        "scrypt$16384$8$1$@@@@notbase64@@@@$BBBB",  # undecodable salt
        "scrypt$16384$8$1$AAAA$BBBB",  # salt/digest wrong length
    ],
)
def test_verify_password_fails_closed_on_malformed(malformed: str) -> None:
    assert verify_password(VALID_PASSWORD, malformed) is False


def test_validate_password_policy_enforces_length_and_blank() -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_policy("x" * (MIN_PASSWORD_LENGTH - 1))
    with pytest.raises(PasswordPolicyError):
        validate_password_policy("x" * (MAX_PASSWORD_LENGTH + 1))
    with pytest.raises(PasswordPolicyError):
        validate_password_policy(" " * MIN_PASSWORD_LENGTH)
    # The floor and ceiling themselves are accepted.
    validate_password_policy("x" * MIN_PASSWORD_LENGTH)
    validate_password_policy("x" * MAX_PASSWORD_LENGTH)


def test_hash_password_propagates_policy_error() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("too-short")


# ---------------------------------------------------------------------------
# Lane 2 — fail-closed without PostgreSQL (no database) — always runs
# ---------------------------------------------------------------------------


def test_register_fails_closed_on_the_sqlite_lane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A SQLite target must answer 503, never self-register a customer."""
    from app.customer_auth_routes import router as customer_auth_router

    app = FastAPI()
    app.include_router(customer_auth_router)
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'cw076.sqlite'}")
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    close_pg_pool()
    try:
        with TestClient(app) as client:
            response = client.post(
                REGISTER_PATH, json={"username": "alice", "password": VALID_PASSWORD}
            )
    finally:
        close_pg_pool()
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "REGISTRATION_SERVICE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Lane 3 — registration contract (dedicated migrated PostgreSQL fixture)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registration_dsn() -> Iterator[str]:
    from alembic import command

    require_pg_or_explicit_skip(_pg_dsn())
    dsn = _dedicated_dsn(CW076_DB_NAME)
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{CW076_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{CW076_DB_NAME}"')
    command.upgrade(_alembic_config(dsn), "head")
    try:
        yield dsn
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{CW076_DB_NAME}" WITH (FORCE)')


@pytest.fixture()
def route_state(registration_dsn: str) -> Iterator[str]:
    close_pg_pool()
    with psycopg.connect(registration_dsn, autocommit=True) as conn:
        conn.execute("SET session_replication_role = replica")
        conn.execute("TRUNCATE wallets, users CASCADE")
        conn.execute("SET session_replication_role = DEFAULT")
    yield registration_dsn
    close_pg_pool()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, route_state: str) -> Iterator[TestClient]:
    from app.customer_auth_routes import router as customer_auth_router

    app = FastAPI()
    app.include_router(customer_auth_router)
    monkeypatch.setenv(DATABASE_URL_ENV, route_state)
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    with TestClient(app) as test_client:
        yield test_client


def test_register_creates_user_and_wallet_atomically(client: TestClient) -> None:
    response = client.post(REGISTER_PATH, json={"username": "alice", "password": VALID_PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "alice"
    assert body["display_name"] == "alice"
    user_id = body["user_id"]
    uuid.UUID(user_id)  # a valid UUID string

    # The secret never crosses the boundary: not a field, not anywhere in text.
    assert "password" not in body
    assert "password_hash" not in body
    assert VALID_PASSWORD not in response.text

    with psycopg.connect(_dedicated_dsn(CW076_DB_NAME)) as conn:
        row = conn.execute(
            "SELECT role, registration_source, password_hash FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "customer"
        assert row[1] == "self_register"
        stored_hash = row[2]
        assert stored_hash and stored_hash != VALID_PASSWORD
        assert verify_password(VALID_PASSWORD, stored_hash), "the stored hash must verify"
        wallet = conn.execute(
            "SELECT user_id FROM wallets WHERE user_id = %s", (user_id,)
        ).fetchone()
        assert wallet is not None, "the wallet must be created in the same transaction"


def test_register_duplicate_username_is_409(client: TestClient) -> None:
    first = client.post(REGISTER_PATH, json={"username": "bob", "password": VALID_PASSWORD})
    assert first.status_code == 201, first.text
    second = client.post(REGISTER_PATH, json={"username": "bob", "password": VALID_PASSWORD})
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "USERNAME_TAKEN"
    with psycopg.connect(_dedicated_dsn(CW076_DB_NAME)) as conn:
        count = conn.execute("SELECT count(*) FROM users WHERE username = 'bob'").fetchone()[0]
    assert count == 1, "the rejected duplicate must not create a second account"


def test_register_trims_surrounding_whitespace(client: TestClient) -> None:
    response = client.post(
        REGISTER_PATH, json={"username": "  carol  ", "password": VALID_PASSWORD}
    )
    assert response.status_code == 201, response.text
    assert response.json()["username"] == "carol"


@pytest.mark.parametrize(
    "username",
    ["ab", "a" * 33, "has space", "bad@char", "semi;colon", "tab\tchar"],
)
def test_register_invalid_username_is_400(client: TestClient, username: str) -> None:
    response = client.post(REGISTER_PATH, json={"username": username, "password": VALID_PASSWORD})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "INVALID_USERNAME"


def test_register_whitespace_only_username_is_400(client: TestClient) -> None:
    response = client.post(REGISTER_PATH, json={"username": "   ", "password": VALID_PASSWORD})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "INVALID_USERNAME"


def test_register_weak_password_is_400_and_creates_nothing(client: TestClient) -> None:
    response = client.post(REGISTER_PATH, json={"username": "dave", "password": "short"})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "WEAK_PASSWORD"
    with psycopg.connect(_dedicated_dsn(CW076_DB_NAME)) as conn:
        count = conn.execute("SELECT count(*) FROM users WHERE username = 'dave'").fetchone()[0]
    assert count == 0, "a rejected password must not create an account"


def test_register_rejects_unknown_body_fields(client: TestClient) -> None:
    response = client.post(
        REGISTER_PATH,
        json={"username": "erin", "password": VALID_PASSWORD, "email": "erin@example.com"},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Lane 4 — registration revision schema guards (own dedicated database)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def migration_dsn() -> Iterator[str]:
    from alembic import command

    require_pg_or_explicit_skip(_pg_dsn())
    dsn = _dedicated_dsn(CW076_MIGRATION_DB_NAME)
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{CW076_MIGRATION_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{CW076_MIGRATION_DB_NAME}"')
    command.upgrade(_alembic_config(dsn), "head")
    try:
        yield dsn
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{CW076_MIGRATION_DB_NAME}" WITH (FORCE)')


def test_registration_revision_adds_credential_columns_and_checks(migration_dsn: str) -> None:
    with psycopg.connect(migration_dsn) as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users'"
            ).fetchall()
        }
        constraints = {
            row[0]
            for row in conn.execute(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'public' AND t.relname = 'users' AND c.contype = 'c'"
            ).fetchall()
        }
    assert {"password_hash", "registration_source"} <= columns
    assert {
        "ck_users_password_hash_not_blank",
        "ck_users_registration_source_known",
        "ck_users_self_register_has_password",
    } <= constraints


def test_registration_revision_rejects_self_register_without_password(migration_dsn: str) -> None:
    with psycopg.connect(migration_dsn) as conn:
        with pytest.raises(CheckViolation):
            conn.execute(
                "INSERT INTO users (id, username, display_name, role, registration_source) "
                "VALUES (%s, %s, %s, 'customer', 'self_register')",
                (str(uuid.uuid4()), "nopass", "nopass"),
            )
        conn.rollback()


def test_registration_revision_rejects_blank_password_hash(migration_dsn: str) -> None:
    with psycopg.connect(migration_dsn) as conn:
        with pytest.raises(CheckViolation):
            conn.execute(
                "INSERT INTO users (id, username, display_name, role, password_hash) "
                "VALUES (%s, %s, %s, 'customer', '   ')",
                (str(uuid.uuid4()), "blankhash", "blankhash"),
            )
        conn.rollback()


def test_registration_revision_rejects_unknown_registration_source(migration_dsn: str) -> None:
    with psycopg.connect(migration_dsn) as conn:
        with pytest.raises(CheckViolation):
            conn.execute(
                "INSERT INTO users "
                "(id, username, display_name, role, password_hash, registration_source) "
                "VALUES (%s, %s, %s, 'customer', %s, 'carrier_pigeon')",
                (str(uuid.uuid4()), "badsrc", "badsrc", hash_password(VALID_PASSWORD)),
            )
        conn.rollback()


def test_registration_revision_allows_a_credential_less_internal_account(
    migration_dsn: str,
) -> None:
    """The columns stay NULL-able for the admin/activation/bootstrap lanes."""
    user_id = str(uuid.uuid4())
    with psycopg.connect(migration_dsn) as conn:
        conn.execute(
            "INSERT INTO users (id, username, display_name, role) VALUES (%s, %s, %s, 'admin')",
            (user_id, "internal-acct", "internal-acct"),
        )
        row = conn.execute(
            "SELECT password_hash, registration_source FROM users WHERE id = %s", (user_id,)
        ).fetchone()
    assert row == (None, None)


def test_registration_revision_downgrade_guard_refuses_then_succeeds_symmetrically(
    migration_dsn: str,
) -> None:
    from alembic import command

    config = _alembic_config(migration_dsn)
    user_id = str(uuid.uuid4())
    with psycopg.connect(migration_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO users "
            "(id, username, display_name, role, password_hash, registration_source) "
            "VALUES (%s, %s, %s, 'customer', %s, 'self_register')",
            (user_id, "guarded", "guarded", hash_password(VALID_PASSWORD)),
        )

    # A credentialed account blocks the downgrade and leaves the pointer at the head.
    with pytest.raises(RuntimeError, match="cannot downgrade 20260912T1400"):
        command.downgrade(config, PRIOR_REVISION)
    with psycopg.connect(migration_dsn) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            HEAD_REVISION
        )

    # Once the credentialed row is gone the downgrade succeeds symmetrically.
    with psycopg.connect(migration_dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM wallets WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    command.downgrade(config, PRIOR_REVISION)
    with psycopg.connect(migration_dsn) as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users'"
            ).fetchall()
        }
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            PRIOR_REVISION
        )
    assert "password_hash" not in columns
    assert "registration_source" not in columns

    # Restore head so this rehearsal cannot disturb any later test in the module.
    command.upgrade(config, "head")
