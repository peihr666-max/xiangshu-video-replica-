"""C5 publish module: platform publish accounts, records and the worker chain.

The publish page previously existed in the studio shell with every real action
disabled ("接口未接通") and drafts kept in React memory only. These tests lock
the cloud contract that unlocks it:

- publish accounts hold platform cookies encrypted at rest (Fernet) and never
  return credential material through the API;
- publish records persist drafts (refresh-safe) and queue real publishes
  against an owned video asset, with an optional cover asset and schedule;
- the worker claims queued publishes with a CAS lease, serializes publishes
  per account, and writes back platform item ids / short links;
- account verification is an async worker probe that flips
  connected/invalid status without ever exposing the cookie;
- /api/studio/stats gains the real published counter (C5 replaces the "—").
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.auth import get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.main import app
from app.publish import (
    claim_account_verify_work,
    claim_publish_work,
    finalize_account_verify,
    finalize_publish_work,
)
from app.publishers.base import PublishResult
from app.settings import LOCAL_KEYSTORE_DISABLED_ENV, SETTINGS_KEY_ENV

_TEST_KEY = Fernet.generate_key().decode("ascii")

_DOUYIN_COOKIE = "sessionid=douyin-test-cookie-value; ttwid=1" + "0" * 32
_SECURITY_SDK = '{"key_version": 3, "ticket": "test-ticket", "data": "' + "x" * 64 + '"}'


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[Path]:
    db_path = tmp_path / "publish.db"
    with initialize_database(db_path) as conn:
        seed_data(conn)
    yield db_path


@pytest.fixture()
def client(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    # Migrated routes (BusinessDb.write) open their own SQLite connection from
    # the env path; it must point at the same database the override yields.
    monkeypatch.setenv("VIDEO_REPLICA_DB_PATH", str(db_path))
    # Credential encryption must never fall back to the OS keystore in tests.
    monkeypatch.setenv(SETTINGS_KEY_ENV, _TEST_KEY)
    monkeypatch.setenv(LOCAL_KEYSTORE_DISABLED_ENV, "1")

    def database_override() -> Iterator[BusinessConnection]:
        conn = BusinessConnection.sqlite(connect_database(db_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_database] = database_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def seed_data(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
        [
            ("employee_1", "employee_1", "Employee One", "employee"),
            ("employee_2", "employee_2", "Employee Two", "employee"),
            ("auditor_1", "auditor_1", "Auditor One", "auditor"),
        ],
    )
    for asset_id, kind, owner in (
        ("video_1", "video", "employee_1"),
        ("video_2", "video", "employee_2"),
        ("cover_1", "material_image", "employee_1"),
        ("not_video", "material_image", "employee_1"),
    ):
        conn.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes,"
            " content_type, created_by_user_id) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)",
            (
                asset_id,
                kind,
                f"local://assets/{asset_id}.bin",
                "sha256:" + asset_id,
                128,
                "video/mp4",
                owner,
            ),
        )


def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Dev-User-Id": user_id}


ACCOUNTS_URL = "/api/studio/publish/accounts"
RECORDS_URL = "/api/studio/publish/records"


def account_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "platform": "douyin",
        "display_name": "乡墅张工",
        "cookie": _DOUYIN_COOKIE,
        "security_sdk": _SECURITY_SDK,
    }
    body.update(overrides)
    return body


def create_account(
    client: TestClient,
    *,
    owner: str = "employee_1",
    **overrides: object,
) -> dict[str, object]:
    response = client.post(
        ACCOUNTS_URL, json=account_body(**overrides), headers=auth_headers(owner)
    )
    assert response.status_code == 200, response.text
    return response.json()


def record_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "asset_id": "video_1",
        "platform": "douyin",
        "title": "三层乡墅实拍",
        "description": "全屋揭秘",
        "tags": ["乡墅", "自建房"],
        "cover_asset_id": "cover_1",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_create_douyin_account_requires_security_sdk(client: TestClient) -> None:
    response = client.post(
        ACCOUNTS_URL,
        json=account_body(security_sdk=None),
        headers=auth_headers("employee_1"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PUBLISH_SECURITY_SDK_REQUIRED"


def test_create_account_roundtrip_and_credential_never_returned(
    client: TestClient,
) -> None:
    created = create_account(client)
    assert created["platform"] == "douyin"
    assert created["display_name"] == "乡墅张工"
    assert created["status"] == "connected"
    assert created["security_sdk_required"] is True
    serialized = repr(created)
    assert _DOUYIN_COOKIE not in serialized
    assert _SECURITY_SDK not in serialized
    assert "cookie" not in created
    assert "security_sdk" not in created

    listed = client.get(ACCOUNTS_URL, headers=auth_headers("employee_1"))
    assert listed.status_code == 200
    accounts = listed.json()["accounts"]
    assert [item["display_name"] for item in accounts] == ["乡墅张工"]


def test_channel_account_omits_security_sdk(client: TestClient) -> None:
    created = create_account(
        client, platform="wechat_channels", display_name="视频号小墅", security_sdk=None
    )
    assert created["platform"] == "wechat_channels"
    assert created["security_sdk_required"] is False


def test_cookie_is_encrypted_at_rest(db_path: Path, client: TestClient) -> None:
    created = create_account(client)
    raw = sqlite3.connect(db_path)
    try:
        row = raw.execute(
            "SELECT cookie_enc, security_sdk_enc FROM publish_accounts WHERE id = ?",
            (created["id"],),
        ).fetchone()
    finally:
        raw.close()
    assert row is not None
    cookie_enc, sdk_enc = row
    assert cookie_enc != _DOUYIN_COOKIE
    assert cookie_enc.startswith("gAAAAA")
    assert sdk_enc != _SECURITY_SDK
    assert _DOUYIN_COOKIE not in Path(db_path).read_bytes().decode("utf-8", errors="ignore")


def test_accounts_are_user_scoped(client: TestClient) -> None:
    create_account(client, owner="employee_1")
    create_account(client, owner="employee_2", display_name="别人家的号")
    mine = client.get(ACCOUNTS_URL, headers=auth_headers("employee_1")).json()["accounts"]
    assert [item["display_name"] for item in mine] == ["乡墅张工"]


def test_delete_account_is_owner_scoped(client: TestClient) -> None:
    created = create_account(client)
    foreign = client.delete(f"{ACCOUNTS_URL}/{created['id']}", headers=auth_headers("employee_2"))
    assert foreign.status_code == 404
    removed = client.delete(f"{ACCOUNTS_URL}/{created['id']}", headers=auth_headers("employee_1"))
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert client.get(ACCOUNTS_URL, headers=auth_headers("employee_1")).json()["accounts"] == []


def test_verify_request_marks_account(client: TestClient, db_path: Path) -> None:
    created = create_account(client)
    response = client.post(
        f"{ACCOUNTS_URL}/{created['id']}/verify", headers=auth_headers("employee_1")
    )
    assert response.status_code == 200
    assert response.json()["submitted"] is True
    foreign = client.post(
        f"{ACCOUNTS_URL}/{created['id']}/verify", headers=auth_headers("employee_2")
    )
    assert foreign.status_code == 404
    raw = sqlite3.connect(db_path)
    try:
        flag = raw.execute(
            "SELECT verify_requested FROM publish_accounts WHERE id = ?",
            (created["id"],),
        ).fetchone()[0]
    finally:
        raw.close()
    assert flag == 1


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def test_create_record_draft_persists(client: TestClient) -> None:
    created = client.post(RECORDS_URL, json=record_body(), headers=auth_headers("employee_1"))
    assert created.status_code == 200, created.text
    record = created.json()
    assert record["status"] == "draft"
    assert record["tags"] == ["乡墅", "自建房"]
    fetched = client.get(RECORDS_URL, headers=auth_headers("employee_1"))
    assert [item["id"] for item in fetched.json()["records"]] == [record["id"]]


def test_record_submit_requires_account(client: TestClient) -> None:
    response = client.post(
        RECORDS_URL,
        json=record_body(submit=True),
        headers=auth_headers("employee_1"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PUBLISH_ACCOUNT_REQUIRED"


def test_record_submit_queues(client: TestClient) -> None:
    account = create_account(client)
    response = client.post(
        RECORDS_URL,
        json=record_body(submit=True, account_id=account["id"]),
        headers=auth_headers("employee_1"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"


def test_record_asset_must_exist_and_be_owned(client: TestClient) -> None:
    missing = client.post(
        RECORDS_URL,
        json=record_body(asset_id="nope"),
        headers=auth_headers("employee_1"),
    )
    assert missing.status_code == 404
    foreign = client.post(
        RECORDS_URL,
        json=record_body(asset_id="video_2"),
        headers=auth_headers("employee_1"),
    )
    assert foreign.status_code == 404
    wrong_kind = client.post(
        RECORDS_URL,
        json=record_body(asset_id="not_video"),
        headers=auth_headers("employee_1"),
    )
    assert wrong_kind.status_code == 422
    assert wrong_kind.json()["detail"]["code"] == "PUBLISH_ASSET_NOT_VIDEO"


def test_record_cover_must_be_owned_image(client: TestClient) -> None:
    foreign_cover = client.post(
        RECORDS_URL,
        json=record_body(cover_asset_id="video_2"),
        headers=auth_headers("employee_1"),
    )
    assert foreign_cover.status_code == 404
    image_cover = client.post(
        RECORDS_URL,
        json=record_body(cover_asset_id="cover_1"),
        headers=auth_headers("employee_1"),
    )
    assert image_cover.status_code == 200


def test_patch_edits_draft_only(client: TestClient) -> None:
    created = client.post(
        RECORDS_URL, json=record_body(), headers=auth_headers("employee_1")
    ).json()
    account = create_account(client)
    patched = client.patch(
        f"{RECORDS_URL}/{created['id']}",
        json={"title": "改后的标题", "account_id": account["id"]},
        headers=auth_headers("employee_1"),
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "改后的标题"

    submitted = client.post(
        f"{RECORDS_URL}/{created['id']}/submit", headers=auth_headers("employee_1")
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "queued"
    locked = client.patch(
        f"{RECORDS_URL}/{created['id']}",
        json={"title": "入队后不该改得动"},
        headers=auth_headers("employee_1"),
    )
    assert locked.status_code == 409
    assert locked.json()["detail"]["code"] == "PUBLISH_RECORD_NOT_DRAFT"


def test_submit_then_cancel_then_delete_lifecycle(client: TestClient) -> None:
    account = create_account(client)
    created = client.post(
        RECORDS_URL,
        json=record_body(submit=True, account_id=account["id"]),
        headers=auth_headers("employee_1"),
    ).json()
    delete_while_queued = client.delete(
        f"{RECORDS_URL}/{created['id']}", headers=auth_headers("employee_1")
    )
    assert delete_while_queued.status_code == 409
    canceled = client.post(
        f"{RECORDS_URL}/{created['id']}/cancel", headers=auth_headers("employee_1")
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    deleted = client.delete(f"{RECORDS_URL}/{created['id']}", headers=auth_headers("employee_1"))
    assert deleted.status_code == 200


def test_records_are_user_scoped(client: TestClient) -> None:
    client.post(RECORDS_URL, json=record_body(), headers=auth_headers("employee_1"))
    foreign = client.get(RECORDS_URL, headers=auth_headers("employee_2"))
    assert foreign.json()["records"] == []
    record = client.post(
        RECORDS_URL,
        json=record_body(asset_id="video_2", cover_asset_id=None),
        headers=auth_headers("employee_2"),
    ).json()
    foreign_delete = client.delete(
        f"{RECORDS_URL}/{record['id']}", headers=auth_headers("employee_1")
    )
    assert foreign_delete.status_code == 404


def test_stats_includes_published_total(client: TestClient, db_path: Path) -> None:
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "INSERT INTO publish_accounts (id, user_id, platform, display_name,"
            " cookie_enc, status) VALUES ('acc_1', 'employee_1', 'douyin', '号',"
            " 'gAAAAA-enc', 'connected')"
        )
        raw.execute(
            "INSERT INTO publish_records (id, user_id, asset_id, platform, account_id,"
            " status, published_at) VALUES"
            " ('rec_1', 'employee_1', 'video_1', 'douyin', 'acc_1', 'published',"
            "  '2026-09-07 01:00:00'),"
            " ('rec_2', 'employee_1', 'video_1', 'douyin', 'acc_1', 'published',"
            "  '2026-09-07 02:00:00'),"
            " ('rec_3', 'employee_1', 'video_1', 'douyin', 'acc_1', 'failed', NULL)"
        )
        raw.commit()
    finally:
        raw.close()
    stats = client.get("/api/studio/stats", headers=auth_headers("employee_1")).json()
    assert stats["published_total"] == 2
    other = client.get("/api/studio/stats", headers=auth_headers("employee_2")).json()
    assert other["published_total"] == 0


# ---------------------------------------------------------------------------
# Worker chain (claim / finalize on the domain layer, adapters faked)
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> BusinessConnection:
    return BusinessConnection.sqlite(connect_database(db_path))


def _seed_queued_record(
    db_path: Path,
    *,
    record_id: str = "rec_q1",
    account_id: str = "acc_1",
    schedule_at: str | None = None,
    status: str = "queued",
    user_id: str = "employee_1",
) -> None:
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "INSERT OR IGNORE INTO publish_accounts (id, user_id, platform,"
            " display_name, cookie_enc, security_sdk_enc, status)"
            " VALUES ('acc_1', ?, 'douyin', '号', 'gAAAAA-enc', NULL, 'connected')",
            (user_id,),
        )
        raw.execute(
            "INSERT INTO publish_records (id, user_id, asset_id, platform, account_id,"
            " title, description, tags_json, cover_asset_id, schedule_at, status)"
            " VALUES (?, ?, 'video_1', 'douyin', ?, '标题', '描述', '[]', 'cover_1',"
            " ?, ?)",
            (record_id, user_id, account_id, schedule_at, status),
        )
        raw.commit()
    finally:
        raw.close()


def test_claim_respects_schedule_and_status(db_path: Path) -> None:
    _seed_queued_record(db_path, schedule_at="2099-01-01 00:00:00")
    with _connect(db_path) as conn:
        assert claim_publish_work(conn, worker_id="w1") is None
    raw = sqlite3.connect(db_path)
    raw.execute(
        "UPDATE publish_records SET schedule_at = '2020-01-01 00:00:00' WHERE id = 'rec_q1'"
    )
    raw.commit()
    raw.close()
    with _connect(db_path) as conn:
        lease = claim_publish_work(conn, worker_id="w1")
        assert lease is not None
        assert lease.kind == "publish"
        assert lease.row["status"] == "publishing"
        # already claimed — a second claim finds nothing for this account
        assert claim_publish_work(conn, worker_id="w2") is None


def test_claim_serializes_same_account_but_not_other_accounts(db_path: Path) -> None:
    _seed_queued_record(db_path, record_id="rec_a")
    _seed_queued_record(db_path, record_id="rec_b")
    raw = sqlite3.connect(db_path)
    raw.execute(
        "INSERT INTO publish_accounts (id, user_id, platform, display_name,"
        " cookie_enc, status) VALUES ('acc_2', 'employee_1', 'douyin', '号2',"
        " 'gAAAAA-enc', 'connected')"
    )
    raw.execute(
        "INSERT INTO publish_records (id, user_id, asset_id, platform, account_id,"
        " title, description, tags_json, cover_asset_id, schedule_at, status)"
        " VALUES ('rec_c', 'employee_1', 'video_1', 'douyin', 'acc_2', '标题',"
        " '描述', '[]', NULL, NULL, 'queued')"
    )
    raw.commit()
    raw.close()
    with _connect(db_path) as conn:
        first = claim_publish_work(conn, worker_id="w1")
        assert first is not None and first.record_id == "rec_a"
        second = claim_publish_work(conn, worker_id="w1")
        assert second is not None and second.record_id == "rec_c"
        assert claim_publish_work(conn, worker_id="w1") is None


def test_finalize_publish_success(db_path: Path) -> None:
    _seed_queued_record(db_path)
    with _connect(db_path) as conn:
        lease = claim_publish_work(conn, worker_id="w1")
        assert lease is not None
        finalize_publish_work(
            conn,
            lease=lease,
            result=PublishResult(
                platform="douyin",
                status="published",
                item_id="7123456789",
                short_url=None,
            ),
        )
    raw = sqlite3.connect(db_path)
    row = raw.execute(
        "SELECT status, platform_item_id, published_at, lease_owner"
        " FROM publish_records WHERE id = 'rec_q1'"
    ).fetchone()
    raw.close()
    assert row is not None
    assert row[0] == "published"
    assert row[1] == "7123456789"
    assert row[2] is not None
    assert row[3] is None


def test_finalize_publish_failure_can_invalidate_account(db_path: Path) -> None:
    _seed_queued_record(db_path)
    with _connect(db_path) as conn:
        lease = claim_publish_work(conn, worker_id="w1")
        assert lease is not None
        finalize_publish_work(
            conn,
            lease=lease,
            result=PublishResult(
                platform="douyin",
                status="failed",
                item_id=None,
                short_url=None,
                message="登录态已失效",
                account_invalid=True,
            ),
        )
    raw = sqlite3.connect(db_path)
    record = raw.execute(
        "SELECT status, error_message FROM publish_records WHERE id = 'rec_q1'"
    ).fetchone()
    account = raw.execute("SELECT status FROM publish_accounts WHERE id = 'acc_1'").fetchone()
    raw.close()
    assert record[0] == "failed"
    assert record[1] == "登录态已失效"
    assert account[0] == "invalid"


def test_account_verify_claim_and_finalize(db_path: Path) -> None:
    _seed_queued_record(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("UPDATE publish_accounts SET verify_requested = 1 WHERE id = 'acc_1'")
    raw.commit()
    raw.close()
    with _connect(db_path) as conn:
        lease = claim_account_verify_work(conn, worker_id="w1")
        assert lease is not None
        assert lease.kind == "account_verify"
        assert claim_account_verify_work(conn, worker_id="w1") is None
        finalize_account_verify(
            conn,
            lease=lease,
            ok=False,
            message="Cookie 已失效",
        )
    raw = sqlite3.connect(db_path)
    account = raw.execute(
        "SELECT status, verify_requested, error_message FROM publish_accounts WHERE id = 'acc_1'"
    ).fetchone()
    raw.close()
    assert account[0] == "invalid"
    assert account[1] == 0
    assert account[2] == "Cookie 已失效"


# ---------------------------------------------------------------------------
# Worker round: fake adapters drive the full claim → deliver → finalize chain
# ---------------------------------------------------------------------------


class _FakeStorage:
    def get_object(self, key: str) -> bytes:
        return b"fake-bytes-for-" + key.encode("utf-8")


def _worker_fixture(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    published_result: PublishResult,
) -> dict[str, object]:
    from cryptography.fernet import Fernet

    import app.publish_worker as worker_mod

    fernet = Fernet(_TEST_KEY.encode("ascii"))
    cookie_enc = fernet.encrypt(_DOUYIN_COOKIE.encode("utf-8")).decode("ascii")
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "INSERT INTO publish_accounts (id, user_id, platform, display_name,"
            " cookie_enc, security_sdk_enc, status)"
            " VALUES ('acc_1', 'employee_1', 'douyin', '号', ?, NULL, 'connected')",
            (cookie_enc,),
        )
        raw.execute(
            "INSERT INTO publish_records (id, user_id, asset_id, platform, account_id,"
            " title, description, tags_json, cover_asset_id, schedule_at, status)"
            " VALUES ('rec_w', 'employee_1', 'video_1', 'douyin', 'acc_1', '标题',"
            " '描述', '[\"乡墅\"]', 'cover_1', NULL, 'queued')"
        )
        raw.commit()
    finally:
        raw.close()

    calls: dict[str, object] = {}

    def fake_dispatch_publish(platform: str, **kwargs: object) -> PublishResult:
        calls["platform"] = platform
        calls["kwargs"] = kwargs
        return published_result

    monkeypatch.setattr(worker_mod, "_dispatch_publish", fake_dispatch_publish)
    monkeypatch.setattr(
        worker_mod,
        "_dispatch_probe",
        lambda platform, cookie, security_sdk: (True, None),
    )
    return {"calls": calls, "fernet": fernet, "worker_mod": worker_mod}


def test_worker_round_publishes_end_to_end(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = _worker_fixture(
        db_path,
        monkeypatch,
        published_result=PublishResult(
            platform="douyin",
            status="published",
            item_id="7100000001",
            short_url="https://v.douyin.com/abc/",
        ),
    )
    with _connect(db_path) as conn:
        processed = setup["worker_mod"].run_publish_round(  # type: ignore[attr-defined]
            conn, worker_id="w1", storage=_FakeStorage(), fernet=setup["fernet"]
        )
    assert processed == 1
    raw = sqlite3.connect(db_path)
    row = raw.execute(
        "SELECT status, platform_item_id, short_url, published_at, error_message"
        " FROM publish_records WHERE id = 'rec_w'"
    ).fetchone()
    raw.close()
    assert row is not None
    assert row[0] == "published"
    assert row[1] == "7100000001"
    assert row[2] == "https://v.douyin.com/abc/"
    assert row[3] is not None
    assert row[4] is None
    kwargs = setup["calls"]["kwargs"]
    assert kwargs is not None and kwargs["title"] == "标题"  # type: ignore[union-attr]
    assert kwargs["tags"] == ["乡墅"]  # type: ignore[union-attr]
    assert kwargs["cookie"] == _DOUYIN_COOKIE  # type: ignore[union-attr]


def test_worker_round_failure_marks_account_invalid(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = _worker_fixture(
        db_path,
        monkeypatch,
        published_result=PublishResult(
            platform="douyin",
            status="failed",
            message="登录态已失效",
            account_invalid=True,
        ),
    )
    with _connect(db_path) as conn:
        setup["worker_mod"].run_publish_round(  # type: ignore[attr-defined]
            conn, worker_id="w1", storage=_FakeStorage(), fernet=setup["fernet"]
        )
    raw = sqlite3.connect(db_path)
    record = raw.execute(
        "SELECT status, error_message FROM publish_records WHERE id = 'rec_w'"
    ).fetchone()
    account = raw.execute(
        "SELECT status FROM publish_accounts WHERE id = 'acc_1'"
    ).fetchone()
    raw.close()
    assert record is not None and record[0] == "failed" and record[1] == "登录态已失效"
    assert account is not None and account[0] == "invalid"


def test_worker_round_verifies_invalid_account(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.fernet import Fernet

    import app.publish_worker as worker_mod

    fernet = Fernet(_TEST_KEY.encode("ascii"))
    cookie_enc = fernet.encrypt(_DOUYIN_COOKIE.encode("utf-8")).decode("ascii")
    raw = sqlite3.connect(db_path)
    raw.execute(
        "INSERT INTO publish_accounts (id, user_id, platform, display_name,"
        " cookie_enc, status, verify_requested)"
        " VALUES ('acc_v', 'employee_1', 'wechat_channels', '号', ?, 'connected', 1)",
        (cookie_enc,),
    )
    raw.commit()
    raw.close()

    probes: list[tuple[str, str]] = []

    def fake_probe(platform: str, cookie: str, security_sdk: str | None) -> tuple[bool, str | None]:
        probes.append((platform, cookie))
        return False, "Cookie 已过期"

    monkeypatch.setattr(worker_mod, "_dispatch_probe", fake_probe)
    with _connect(db_path) as conn:
        processed = worker_mod.run_publish_round(
            conn, worker_id="w1", storage=_FakeStorage(), fernet=fernet
        )
    assert processed == 1
    assert probes == [("wechat_channels", _DOUYIN_COOKIE)]
    raw = sqlite3.connect(db_path)
    account = raw.execute(
        "SELECT status, verify_requested, error_message FROM publish_accounts"
        " WHERE id = 'acc_v'"
    ).fetchone()
    raw.close()
    assert account is not None
    assert account == ("invalid", 0, "Cookie 已过期")
