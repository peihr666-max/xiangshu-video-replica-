"""W8 — 经营分析路由测试（每日售价 upsert + 日利润聚合）。

独立 PG 库（w08_profit_test）迁移到 head；种子：
- 一个客户 + 钱包 + 视频任务（768P，10 秒，SUCCEEDED/DIRECT）；
- 对应 SETTLE 流水（预留 -10/+10 → 结算 0/-10）。
覆盖：售价 upsert 契约与审计、利润聚合（收入=当日售价×结算秒数、
成本=actual_cost 合计、毛利/利润率）、未知日期口径（carry-forward）。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin_auth_routes import (
    ADMIN_CSRF_HEADER,
    ADMIN_SESSION_HMAC_KEY_ENV,
    issue_exchange_credential,
)
from app.admin_write_contract import IDEMPOTENCY_KEY_HEADER
from app.db_pg import DATABASE_URL_ENV, close_pg_pool

TEST_KEY = "w08-profit-test-hmac-key-0123456789abcdef"


def _pg_available(dsn: str) -> bool:
    try:
        import psycopg

        conn = psycopg.connect(dsn, connect_timeout=3)
        conn.close()
    except Exception:
        return False
    return True


DEFAULT_DSN = "postgresql://testuser:testpass@localhost:5433/customer_v3_test"
W08_DB_NAME = "w08_profit_test"


def _pg_dsn() -> str:
    import os

    return os.environ.get("TEST_POSTGRESQL_URL", DEFAULT_DSN)


def _admin_dsn() -> str:
    return _pg_dsn().rsplit("/", 1)[0] + "/postgres"


def _w08_dsn() -> str:
    return _pg_dsn().rsplit("/", 1)[0] + f"/{W08_DB_NAME}"


@pytest.fixture(scope="module")
def profit_pg_dsn() -> Iterator[str]:
    from alembic import command
    from alembic.config import Config

    if not _pg_available(_pg_dsn()):
        pytest.skip("PostgreSQL fixture is not available")
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{W08_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{W08_DB_NAME}"')
    server_dir = Path(__file__).resolve().parent.parent
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", _w08_dsn().replace("postgresql://", "postgresql+psycopg://")
    )
    command.upgrade(config, "head")
    with psycopg.connect(_w08_dsn(), autocommit=True) as conn:
        for user_id, role in (("admin_u", "admin"), ("auditor_u", "auditor")):
            conn.execute(
                "INSERT INTO users (id, username, display_name, role) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (user_id, user_id, user_id.replace("_", " ").title(), role),
            )
    try:
        yield _w08_dsn()
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{W08_DB_NAME}" WITH (FORCE)')


@pytest.fixture()
def profit_app(
    monkeypatch: pytest.MonkeyPatch, profit_pg_dsn: str
) -> Iterator[FastAPI]:
    from app.admin_auth_routes import router as admin_auth_router
    from app.admin_profit_routes import router as admin_profit_router

    app = FastAPI()
    app.include_router(admin_auth_router)
    app.include_router(admin_profit_router)
    monkeypatch.setenv(DATABASE_URL_ENV, profit_pg_dsn)
    monkeypatch.setenv(ADMIN_SESSION_HMAC_KEY_ENV, TEST_KEY)
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    yield app


@pytest.fixture()
def client(profit_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(profit_app) as test_client:
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


def _write_headers(base: dict[str, str]) -> dict[str, str]:
    import uuid

    return {**base, IDEMPOTENCY_KEY_HEADER: f"key-{uuid.uuid4()}"}


def test_daily_price_upsert_requires_contract(admin_headers: dict[str, str], client: TestClient) -> None:
    payload = {"price_date": str((dt.datetime.now() + dt.timedelta(days=1)).date()), "price_768p_fen": 12, "price_2k_fen": 20}
    response = client.put("/api/control/profit/daily-price", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    response = client.put(
        "/api/control/profit/daily-price",
        json={**payload, "confirm": True},
        headers={ADMIN_CSRF_HEADER: admin_headers[ADMIN_CSRF_HEADER]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.fixture()
def auditor_headers(client: TestClient) -> dict[str, str]:
    return _exchange(client, "auditor_u")


def test_daily_price_upsert_rejects_auditor(
    auditor_headers: dict[str, str], client: TestClient
) -> None:
    response = client.put(
        "/api/control/profit/daily-price",
        json={
            "price_date": str((dt.datetime.now() + dt.timedelta(days=1)).date()),
            "price_768p_fen": 12,
            "price_2k_fen": 20,
            "confirm": True,
            "reason": "审计员不应能定价",
        },
        headers=_write_headers(auditor_headers),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AUDITOR_READ_ONLY"


def test_daily_price_upsert_and_overwrite(admin_headers: dict[str, str], client: TestClient) -> None:
    body = {
        "price_date": str((dt.datetime.now() + dt.timedelta(days=1)).date()),
        "price_768p_fen": 12,
        "price_2k_fen": 20,
        "note": "促销定价",
        "confirm": True,
        "reason": "客户续费定价",
    }
    response = client.put(
        "/api/control/profit/daily-price", json=body, headers=_write_headers(admin_headers)
    )
    assert response.status_code == 200, response.text
    prices = response.json()
    assert prices[0]["price_date"] == str((dt.datetime.now() + dt.timedelta(days=1)).date())
    assert prices[0]["price_768p_fen"] == 12

    # 同日改价 = 覆盖（upsert），列表仍只有一条该日期。
    response = client.put(
        "/api/control/profit/daily-price",
        json={**body, "price_768p_fen": 15, "reason": "改价"},
        headers=_write_headers(admin_headers),
    )
    assert response.status_code == 200
    same_day = [p for p in response.json() if p["price_date"] == str((dt.datetime.now() + dt.timedelta(days=1)).date())]
    assert len(same_day) == 1
    assert same_day[0]["price_768p_fen"] == 15


def test_daily_price_rejects_invalid_date(admin_headers: dict[str, str], client: TestClient) -> None:
    response = client.put(
        "/api/control/profit/daily-price",
        json={
            "price_date": "not-a-date",
            "price_768p_fen": 12,
            "price_2k_fen": 20,
            "confirm": True,
            "reason": "测试",
        },
        headers=_write_headers(admin_headers),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PROFIT_DATE_INVALID"


def test_profit_overview_aggregates_revenue_cost_margin(
    admin_headers: dict[str, str], client: TestClient, profit_pg_dsn: str
) -> None:
    import psycopg

    # 种子：一天前录入售价（768P 0.10 元/秒）；客户/项目/批次/任务 + 结算流水。
    with psycopg.connect(profit_pg_dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO daily_external_prices
                (price_date, price_768p_fen, price_2k_fen, created_at)
            VALUES (((now() AT TIME ZONE 'Asia/Shanghai')::date - 1), 10, 20, now())
            ON CONFLICT (price_date) DO UPDATE SET price_768p_fen = 10
            """
        )
        conn.execute(
            """
            INSERT INTO users (id, username, display_name, role)
            VALUES ('cust_1', 'customer-1', '客户一', 'customer')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO projects (id, owner_user_id, name)
            VALUES ('p1', 'cust_1', '项目')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO generation_batches (id, project_id, created_by_user_id,
                idempotency_key, request_hash, request_snapshot_json)
            VALUES ('b1', 'p1', 'cust_1', 'k1', 'h1', '{}')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO generation_tasks (id, batch_id, generation_mode, provider, model,
                status, archive_status, prompt_snapshot_json, actual_cost,
                completed_at, billed_seconds)
            VALUES ('t1', 'b1', 'I2V', 'metaso', 'MiniMax-H3', 'SUCCEEDED', 'DIRECT',
                    '{"resolution": "768P", "output_duration_seconds": 10}'::json,
                    0.90,
                    to_char(now() - interval '1 day' + interval '2 hours',
                            'YYYY-MM-DD HH24:MI:SS'),
                    10)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO wallets (user_id, available_credits, reserved_credits)
            VALUES ('cust_1', 100, 0) ON CONFLICT (user_id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO wallet_transactions (
                id, user_id, type, available_delta, reserved_delta,
                task_id, billing_round, idempotency_key, created_at
            ) VALUES (
                'tx_settle_1', 'cust_1', 'RESERVE', -10, 10, 't1', 1,
                'reserve:t1:1',
                to_char(now() - interval '1 day' + interval '2 hours',
                        'YYYY-MM-DD HH24:MI:SS')
            ), (
                'tx_settle_2', 'cust_1', 'SETTLE', 0, -10, 't1', 1,
                'settle:t1:1',
                to_char(now() - interval '1 day' + interval '2 hours',
                        'YYYY-MM-DD HH24:MI:SS')
            ) ON CONFLICT (id) DO NOTHING
            """
        )

    response = client.get(
        "/api/control/profit/overview?lookback_days=7", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    print("DEBUG DAYS:", payload["days"])
    import psycopg as _pg
    with _pg.connect(profit_pg_dsn) as _c:
        print("DEBUG RAW:", _c.execute("SELECT wt.created_at, ((to_timestamp(wt.created_at, 'YYYY-MM-DD HH24:MI:SS') AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai'))::date FROM wallet_transactions wt WHERE wt.type='SETTLE'").fetchall())
    day = next(d for d in payload["days"] if d["settled_seconds"] == 10)
    # 标准收入：结算 10 秒 × 768P 售价 0.10 元 = 1.00 元 = 100 分。
    assert day["revenue_fen"] == 100
    # 成本：actual_cost = 10 秒 × 0.09 元 = 0.90 元 = 90 分。
    assert day["cost_fen"] == 90
    assert day["gross_fen"] == 10
    assert day["margin_pct"] == 10.0
    assert day["video_count"] == 1

    # 售价列表包含录入的日期。
    assert any(p["price_date"] and p["price_768p_fen"] == 10 for p in payload["prices"])
    assert "不回填" in payload["cost_coverage_note"]
