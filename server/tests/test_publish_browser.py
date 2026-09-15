"""Real PG ownership/encryption/cancellation; platform browser responses are fixtures."""

import json
import os
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_publish_accounts import (
    _clear_dependency_overrides,
    _PgBusinessDb,
    actor,
    client,
    cw068_dsn,
    holder,
    lane_env,
    pg,
)

from app import publish_browser_routes as routes
from app.db_pg import pg_transaction
from app.publish_browser_engine import BrowserEvent, parse_identity
from app.settings import SETTINGS_KEY_ENV

__all__ = ["_clear_dependency_overrides", "client", "cw068_dsn", "holder", "lane_env", "pg"]
BASE = "/api/studio/publish/browser"


@pytest.mark.parametrize("platform", ["douyin", "wechat_channels", "xiaohongshu"])
def test_browser_scan_encrypts_state_and_never_streams_secrets(
    client: TestClient,
    pg: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    secret = "temporary-" + uuid4().hex
    storage = {"cookies": [{"name": "session", "value": secret}], "origins": []}

    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        yield BrowserEvent("qr_ready", image="data:image/png;base64,cXI=")
        yield BrowserEvent(
            "connected",
            identity={"platform_user_id": "uid-1", "username": "平台昵称"},
            storage=storage,
        )

    monkeypatch.setattr(routes, "login_events", events)
    response = client.post(BASE + "/logins", json={"platform": platform})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = [json.loads(line) for line in response.text.splitlines()]
    assert [event["phase"] for event in data] == ["loading", "qr_ready", "connected"]
    assert secret not in response.text and "storage" not in response.text
    row = pg.execute("SELECT storage_state_enc FROM publish_browser_accounts").fetchone()
    assert secret not in row[0]
    assert (
        json.loads(Fernet(os.environ[SETTINGS_KEY_ENV].encode()).decrypt(row[0].encode()))
        == storage
    )
    accounts = client.get(BASE + "/accounts")
    assert accounts.json()[0]["platform_user_id"] == "uid-1"
    assert secret not in accounts.text
    assert pg.execute("SELECT count(*) FROM publish_browser_logins").fetchone()[0] == 0
    # Same verified platform identity updates the same account instead of duplicating it.
    client.post(BASE + "/logins", json={"platform": platform})
    assert pg.execute("SELECT count(*) FROM publish_browser_accounts").fetchone()[0] == 1


def test_browser_cancel_prevents_late_account_persistence(
    client: TestClient,
    pg: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        with pg_transaction() as conn:
            conn.execute("DELETE FROM publish_browser_logins WHERE user_id='employee_1'")
        yield BrowserEvent(
            "connected", identity={"platform_user_id": "late", "username": "迟到账号"}, storage={}
        )

    monkeypatch.setattr(routes, "login_events", events)
    response = client.post(BASE + "/logins", json={"platform": "douyin"})
    assert json.loads(response.text.splitlines()[-1])["phase"] == "closed"
    assert pg.execute("SELECT count(*) FROM publish_browser_accounts").fetchone()[0] == 0


def test_browser_accounts_and_relogin_are_owner_scoped(
    client: TestClient,
    holder: _PgBusinessDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        yield BrowserEvent(
            "connected", identity={"platform_user_id": "mine", "username": "我的账号"}, storage={}
        )

    monkeypatch.setattr(routes, "login_events", events)
    client.post(BASE + "/logins", json={"platform": "xiaohongshu"})
    account_id = client.get(BASE + "/accounts").json()[0]["id"]
    holder.current_actor = actor("employee_2")
    assert client.get(BASE + "/accounts").json() == []
    assert client.delete(BASE + "/accounts/" + account_id).status_code == 404
    assert (
        client.post(
            BASE + "/logins", json={"platform": "xiaohongshu", "account_id": account_id}
        ).status_code
        == 404
    )
    holder.current_actor = actor("employee_1")
    assert client.delete(BASE + "/accounts/" + account_id).status_code == 200
    assert client.get(BASE + "/accounts").json() == []


def test_browser_failure_is_redacted_and_releases_capacity(
    client: TestClient,
    pg: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "private-" + uuid4().hex

    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        raise RuntimeError(secret)
        yield BrowserEvent("closed")  # pragma: no cover

    monkeypatch.setattr(routes, "login_events", events)
    response = client.post(BASE + "/logins", json={"platform": "wechat_channels"})
    assert secret not in response.text
    assert json.loads(response.text.splitlines()[-1])["phase"] == "closed"
    assert pg.execute("SELECT count(*) FROM publish_browser_logins").fetchone()[0] == 0


def test_browser_qr_alone_never_marks_an_account_connected(
    client: TestClient,
    pg: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        yield BrowserEvent("qr_ready", image="data:image/png;base64,cXI=")
        yield BrowserEvent("expired")

    monkeypatch.setattr(routes, "login_events", events)
    response = client.post(BASE + "/logins", json={"platform": "douyin"})
    assert json.loads(response.text.splitlines()[-1])["phase"] == "expired"
    assert pg.execute("SELECT count(*) FROM publish_browser_accounts").fetchone()[0] == 0


def test_identity_rejects_failed_and_missing_platform_identity() -> None:
    assert (
        parse_identity("douyin", {"status_code": 8, "user": {"uid": "1", "nickname": "未登录"}})
        is None
    )
    assert parse_identity("xiaohongshu", {"success": True, "data": {"userName": "无ID"}}) is None
    assert parse_identity("wechat_channels", {"errCode": 0, "data": None}) is None
    assert parse_identity(
        "douyin", {"status_code": 0, "user": {"uid": 123, "nickname": "本人"}}
    ) == {"platform_user_id": "123", "username": "本人"}


def test_relogin_wrong_account_preserves_original_encrypted_state(
    client: TestClient, pg: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = "first"
    received: list[Any] = []

    async def events(_: Any, storage: Any) -> AsyncGenerator[BrowserEvent, None]:
        received.append(storage)
        yield BrowserEvent(
            "connected",
            identity={"platform_user_id": uid, "username": uid},
            storage={"origins": []},
        )

    monkeypatch.setattr(routes, "login_events", events)
    client.post(BASE + "/logins", json={"platform": "douyin"})
    original = pg.execute("SELECT id,storage_state_enc FROM publish_browser_accounts").fetchone()
    uid = "different"
    response = client.post(BASE + "/logins", json={"platform": "douyin", "account_id": original[0]})
    assert "扫码账号与原账号不同" in response.text
    assert received == [None, {"origins": []}]
    assert pg.execute("SELECT id,storage_state_enc FROM publish_browser_accounts").fetchall() == [
        original
    ]


def test_changed_actor_during_scan_cannot_persist_and_closes_browser(
    client: TestClient,
    pg: psycopg.Connection,
    holder: _PgBusinessDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        try:
            holder.current_actor = actor("employee_2")
            yield BrowserEvent(
                "connected", identity={"platform_user_id": "late", "username": "late"}, storage={}
            )
        finally:
            closed.append(True)

    monkeypatch.setattr(routes, "login_events", events)
    response = client.post(BASE + "/logins", json={"platform": "douyin"})
    assert "用户会话已变更" in response.text
    assert closed == [True]
    assert pg.execute("SELECT count(*) FROM publish_browser_accounts").fetchone()[0] == 0
    assert pg.execute("SELECT count(*) FROM publish_browser_logins").fetchone()[0] == 0


def test_one_active_scan_per_owner_and_expired_slot_can_be_replaced(
    client: TestClient, pg: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pg_transaction() as conn:
        conn.execute(
            "INSERT INTO publish_browser_logins(id,user_id,platform,expires_at) "
            "VALUES ('busy','employee_1','douyin',clock_timestamp()+interval '1 minute')"
        )
    assert client.post(BASE + "/logins", json={"platform": "douyin"}).status_code == 409
    with pg_transaction() as conn:
        conn.execute(
            "UPDATE publish_browser_logins SET expires_at=clock_timestamp()-interval '1 second'"
        )

    async def events(*_: Any) -> AsyncGenerator[BrowserEvent, None]:
        yield BrowserEvent("expired")

    monkeypatch.setattr(routes, "login_events", events)
    assert client.post(BASE + "/logins", json={"platform": "douyin"}).status_code == 200
    assert pg.execute("SELECT count(*) FROM publish_browser_logins").fetchone()[0] == 0
