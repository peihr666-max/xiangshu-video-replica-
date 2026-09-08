"""Oral digital-human domain tests (C1 slice ②).

Vendor transport is scripted; storage is stubbed at the module seam
(``app.oral.storage_for_asset`` / ``app.oral.get_media_storage``) so these
tests exercise clone flows, task lifecycle, idempotency, and pricing without
network or real buckets.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from app.auth import CurrentUser
from app.db import initialize_database
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient
from app.oral import (
    ORAL_UNIT_PRICE_FEN_DEFAULT,
    CloneOutcome,
    OralDomainError,
    OralOutcome,
    acquire_oral_clone,
    acquire_oral_task,
    confirm_voice_clone,
    create_oral_task,
    finalize_oral_clone_work,
    finalize_oral_task_work,
    oral_unit_price_fen,
    record_oral_clone_consent,
    refresh_avatar_clone,
    refresh_voice_clone,
    run_next_oral_task,
    start_avatar_clone,
    start_voice_clone,
)

_NOW = "2026-09-06 03:00:00"


@pytest.fixture(autouse=True)
def settings_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_REPLICA_SETTINGS_KEY", Fernet.generate_key().decode("ascii"))


class FakeSourceStorage:
    def __init__(self, payload: bytes = b"FAKEMEDIA") -> None:
        self.payload = payload

    def get_object(self, key: str) -> bytes:
        return self.payload


@pytest.fixture()
def fake_source_storage(monkeypatch: pytest.MonkeyPatch) -> FakeSourceStorage:
    storage = FakeSourceStorage()
    monkeypatch.setattr("app.oral.storage_for_asset", lambda _conn, _uri: storage)
    return storage


def actor(user_id: str = "employee_1") -> CurrentUser:
    return CurrentUser(id=user_id, username=user_id, display_name=user_id, role="employee")


def auditor() -> CurrentUser:
    return CurrentUser(id="employee_1", username="auditor", display_name="auditor", role="auditor")


class ScriptedVendorTransport:
    """Routes vendor calls by (method, url-prefix) with canned JSON bodies."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], bytes | Callable[[bytes | None], bytes]] = {}
        self.calls: list[tuple[str, str]] = []

    def on(
        self, method: str, prefix: str, responder: bytes | Callable[[bytes | None], bytes]
    ) -> None:
        self.routes[(method, prefix)] = responder

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> bytes:
        self.calls.append((method, url))
        if method == "PUT":
            return b""
        path = url.split("?", 1)[0]
        for (route_method, prefix), responder in self.routes.items():
            if route_method == method and path.endswith(prefix):
                return responder(body) if callable(responder) else responder
        raise AssertionError(f"unexpected vendor call {method} {url}")


def envelope(data: dict[str, Any]) -> bytes:
    return json.dumps({"code": 0, "msg": "", "data": data}).encode()


def make_vendor() -> tuple[HiflyClient, ScriptedVendorTransport]:
    transport = ScriptedVendorTransport()
    return HiflyClient(api_key="test-key", transport=transport), transport


def seed_scene(tmp_path: Path, name: str) -> BusinessConnection:
    connection = initialize_database(tmp_path / name)
    connection.execute(
        "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
        ("employee_1", "employee_1", "Employee", "employee"),
    )
    connection.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES ('project-1', 'employee_1', 'P')"
    )
    connection.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (
            'asset-auth', NULL, 'identity_authorization', 'local://assets/auth.jpg',
            '', 0, 'image/jpeg', 'employee_1'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO person_identities (
            id, owner_user_id, display_name, status, authorization_status,
            authorization_asset_id, source_quality_status
        ) VALUES (
            'ident-1', 'employee_1', '张工', 'ACTIVE', 'AUTHORIZED',
            'asset-auth', 'PASSED'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        )
        VALUES (
            'asset-src', 'project-1', 'source_video', 'local://assets/src.mp4',
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            0, 'video/mp4', 'employee_1'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        )
        VALUES (
            'asset-audio', 'project-1', 'oral_audio', 'local://assets/v.mp3',
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
            0, 'audio/mpeg', 'employee_1'
        )
        """
    )
    connection.execute(
        "UPDATE assets SET metadata_json = ? WHERE id = 'asset-auth'",
        (
            json.dumps(
                {
                    "identity_id": "ident-1",
                    "purpose": "authorization",
                    "oral_clone_consents": [
                        {
                            "identity_id": "ident-1",
                            "source_asset_id": "asset-src",
                            "source_sha256": "a" * 64,
                            "purpose": "oral_avatar_clone",
                        },
                        {
                            "identity_id": "ident-1",
                            "source_asset_id": "asset-audio",
                            "source_sha256": "b" * 64,
                            "purpose": "oral_voice_clone",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
        ),
    )
    connection.execute(
        "INSERT INTO wallets (user_id, available_credits, reserved_credits) "
        "VALUES ('employee_1', 10, 0)"
    )
    connection.commit()
    return BusinessConnection.sqlite(connection)


def seed_ready_assets(conn: BusinessConnection) -> tuple[str, str]:
    conn.execute(
        """
        INSERT INTO oral_avatars (
            id, identity_id, owner_user_id, title, vendor_avatar_id,
            status, source_kind, source_asset_id
        )
        VALUES (
            'avatar-ready', 'ident-1', 'employee_1', '张工分身',
            'vendor-avatar-9', 'READY', 'VIDEO', 'asset-src'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO oral_voices (
            id, identity_id, owner_user_id, title, vendor_voice_id,
            status, source_asset_id, demo_asset_id, confirmed
        )
        VALUES (
            'voice-ready', 'ident-1', 'employee_1', '张工声音',
            'vendor-voice-9', 'READY', 'asset-audio', 'demo-ready', 1
        )
        """
    )
    conn.commit()
    return "avatar-ready", "voice-ready"


def test_avatar_clone_worker_submits_then_polls_to_ready(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-avatar.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {"upload_url": "https://up.example/1", "content_type": "video/mp4", "file_id": "file-1"}
        ),
    )
    transport.on("POST", "/api/v2/hifly/avatar/create_by_video", envelope({"task_id": "vt-1"}))
    transport.on(
        "GET", "/api/v2/hifly/avatar/task", envelope({"status": 3, "avatar_id": "vendor-avatar-1"})
    )

    started = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="张工口播分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="avatar-clone-1",
    )
    assert started.status == "PENDING"
    from app.oral import acquire_oral_clone, run_claimed_oral_clone

    lease = acquire_oral_clone(conn, worker_id="clone-worker")
    assert lease is not None
    run_claimed_oral_clone(conn, lease=lease, worker_id="clone-worker", vendor=vendor)
    conn.execute(
        "UPDATE oral_avatars SET locked_until = '2000-01-01T00:00:00+00:00' WHERE id = %s",
        (started.task_id,),
    )
    conn.commit()
    lease = acquire_oral_clone(conn, worker_id="clone-worker")
    assert lease is not None
    run_claimed_oral_clone(conn, lease=lease, worker_id="clone-worker", vendor=vendor)
    refreshed = refresh_avatar_clone(conn, avatar_id=started.task_id, actor=actor(), vendor=vendor)
    assert refreshed["status"] == "READY"
    assert refreshed["vendor_avatar_id"] == "vendor-avatar-1"
    # 上传走 PUT；创建与查询各一次 POST/GET。
    assert any(method == "PUT" for method, _ in transport.calls)


def test_voice_clone_archives_demo_but_requires_confirmation(
    tmp_path: Path, fake_source_storage: FakeSourceStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = seed_scene(tmp_path, "oral-voice.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/2",
                "content_type": "audio/mpeg",
                "file_id": "file-2",
            }
        ),
    )
    transport.on("POST", "/api/v2/hifly/voice/create", envelope({"task_id": "vt-2"}))
    transport.on(
        "GET",
        "/api/v2/hifly/voice/task",
        envelope(
            {"status": 3, "voice": "vendor-voice-2", "demo_url": "https://tmp.example/demo.mp3"}
        ),
    )
    transport.on("GET", "https://tmp.example/demo.mp3", b"DEMO")

    from datetime import datetime

    from app.storage import StoredObject

    class DemoStorage:
        def put_object(self, key: str, content: bytes, *, content_type: str):
            return StoredObject(
                provider="fake",
                bucket="assets",
                key=key,
                uri=f"fake://assets/{key}",
                size=len(content),
                content_type=content_type,
                sha256="demo-hash",
                updated_at=datetime.now(tz=UTC),
            )

    monkeypatch.setattr("app.oral.get_media_storage", lambda _conn: DemoStorage())

    started = start_voice_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="张工声音",
        source_asset_id="asset-audio",
        consent_id="asset-auth",
        idempotency_key="voice-clone-1",
    )
    from app.oral import acquire_oral_clone, run_claimed_oral_clone

    lease = acquire_oral_clone(conn, worker_id="voice-worker")
    assert lease is not None
    run_claimed_oral_clone(conn, lease=lease, worker_id="voice-worker", vendor=vendor)
    conn.execute(
        "UPDATE oral_voices SET locked_until = '2000-01-01T00:00:00+00:00' WHERE id = %s",
        (started.task_id,),
    )
    conn.commit()
    lease = acquire_oral_clone(conn, worker_id="voice-worker")
    assert lease is not None
    run_claimed_oral_clone(conn, lease=lease, worker_id="voice-worker", vendor=vendor)
    refreshed = refresh_voice_clone(conn, voice_id=started.task_id, actor=actor(), vendor=vendor)
    assert refreshed["status"] == "READY"
    assert refreshed["vendor_voice_id"] == "vendor-voice-2"
    assert refreshed["confirmed"] == 0
    assert refreshed["demo_asset_id"]


def test_image_avatar_is_queued_and_worker_uses_image_api(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    from app.oral import acquire_oral_clone, run_claimed_oral_clone

    conn = seed_scene(tmp_path, "oral-image-worker.db")
    conn.execute("UPDATE assets SET content_type = 'image/jpeg' WHERE id = 'asset-src'")
    conn.commit()
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/i",
                "content_type": "image/jpeg",
                "file_id": "image-file",
            }
        ),
    )
    transport.on(
        "POST", "/api/v2/hifly/avatar/create_by_image", envelope({"task_id": "image-task"})
    )
    started = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="图片分身",
        source_asset_id="asset-src",
        source_kind="IMAGE",
        consent_id="asset-auth",
        idempotency_key="avatar-image-1",
    )
    assert started.status == "PENDING"
    lease = acquire_oral_clone(conn, worker_id="clone-worker")
    assert lease is not None
    run_claimed_oral_clone(conn, lease=lease, worker_id="clone-worker", vendor=vendor)
    row = conn.execute(
        "SELECT status, vendor_task_id FROM oral_avatars WHERE id = %s",
        (started.task_id,),
    ).fetchone()
    assert tuple(row) == ("RUNNING", "image-task")
    assert any(url.endswith("/avatar/create_by_image") for _, url in transport.calls)
    assert not any(url.endswith("/avatar/create_by_video") for _, url in transport.calls)


def test_create_oral_task_tts_submits_and_replays_idempotently(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-task.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    transport.on("POST", "/api/v2/hifly/video/create_by_tts", envelope({"task_id": "vt-task-1"}))

    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="乡墅口播",
        script_text="大家好，今天带大家看一套乡墅。",
        audio_asset_id=None,
        subtitle={"st_show": True},
        idempotency_key="idem-key-0001",
        vendor=vendor,
    )
    assert created.status == "QUEUED"
    assert created.estimated_cost_fen == ORAL_UNIT_PRICE_FEN_DEFAULT
    assert created.replayed is False
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert tuple(wallet) == (9, 1)
    assert (
        conn.execute(
            "SELECT type FROM wallet_transactions WHERE oral_task_id = %s",
            (created.task_id,),
        ).fetchone()["type"]
        == "RESERVE"
    )

    replayed = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="乡墅口播",
        script_text="大家好，今天带大家看一套乡墅。",
        audio_asset_id=None,
        subtitle={"st_show": True},
        idempotency_key="idem-key-0001",
        vendor=vendor,
    )
    assert replayed.task_id == created.task_id
    assert replayed.replayed is True
    # 幂等重放不再提交供应商：创建调用只有一次。
    assert sum(1 for method, url in transport.calls if url.endswith("/video/create_by_tts")) == 0

    with pytest.raises(OralDomainError, match="不同"):
        create_oral_task(
            conn,
            actor=actor(),
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=voice_id,
            mode="TTS",
            title="已改变标题",
            script_text="大家好，今天带大家看一套乡墅。",
            audio_asset_id=None,
            subtitle={"st_show": True},
            idempotency_key="idem-key-0001",
        )


def test_oral_idempotency_key_is_scoped_by_owner(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-owner-idempotency.db")
    avatar_1, voice_1 = seed_ready_assets(conn)
    conn.execute(
        "INSERT INTO users (id, username, display_name, role) "
        "VALUES ('employee_2', 'employee_2', 'Employee Two', 'employee')"
    )
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES ('project-2', 'employee_2', 'P2')"
    )
    conn.execute(
        "INSERT INTO assets (id, kind, storage_uri, sha256, size_bytes, content_type, "
        "created_by_user_id) VALUES ('asset-auth-2', 'identity_authorization', "
        "'local://assets/auth-2.jpg', '', 0, 'image/jpeg', 'employee_2')"
    )
    conn.execute(
        "INSERT INTO person_identities (id, owner_user_id, display_name, status, "
        "authorization_status, authorization_asset_id, source_quality_status) VALUES "
        "('ident-2', 'employee_2', '李工', 'ACTIVE', 'AUTHORIZED', 'asset-auth-2', 'PASSED')"
    )
    conn.execute(
        "INSERT INTO wallets (user_id, available_credits, reserved_credits) "
        "VALUES ('employee_2', 10, 0)"
    )
    conn.execute(
        "INSERT INTO oral_avatars (id, identity_id, owner_user_id, title, vendor_avatar_id, "
        "status, source_kind, source_asset_id) VALUES "
        "('avatar-2', 'ident-2', 'employee_2', 'A2', 'vendor-a2', 'READY', 'VIDEO', 'x')"
    )
    conn.execute(
        "INSERT INTO oral_voices (id, identity_id, owner_user_id, title, vendor_voice_id, "
        "status, source_asset_id, demo_asset_id, confirmed) VALUES "
        "('voice-2', 'ident-2', 'employee_2', 'V2', 'vendor-v2', 'READY', 'x', 'd2', 1)"
    )
    conn.commit()

    first = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_1,
        voice_id=voice_1,
        mode="TTS",
        title="同键",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="shared-key-1",
    )
    second = create_oral_task(
        conn,
        actor=actor("employee_2"),
        identity_id="ident-2",
        avatar_id="avatar-2",
        voice_id="voice-2",
        mode="TTS",
        title="同键",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="shared-key-1",
    )
    assert first.task_id != second.task_id


def test_create_oral_task_rejects_unready_assets(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-invalid.db")
    vendor, _ = make_vendor()

    with pytest.raises(OralDomainError, match="就绪"):
        create_oral_task(
            conn,
            actor=actor(),
            identity_id="ident-1",
            avatar_id="missing",
            voice_id=None,
            mode="TTS",
            title="t",
            script_text="文案",
            audio_asset_id=None,
            subtitle=None,
            idempotency_key="idem-key-0002",
            vendor=vendor,
        )


def test_refresh_oral_task_archives_result_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = seed_scene(tmp_path, "oral-refresh.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    transport.on("POST", "/api/v2/hifly/video/create_by_tts", envelope({"task_id": "vt-task-2"}))
    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="乡墅口播",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="idem-key-0003",
        vendor=vendor,
    )

    # 首次刷新提交任务，第二次刷新查询 DONE 并归档为平台资产。
    assert run_next_oral_task(conn, worker_id="worker-1", vendor=vendor) == created.task_id
    submitted = conn.execute(
        "SELECT status FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert submitted["status"] == "RUNNING"
    transport.on(
        "GET",
        "/api/v2/hifly/video/task",
        envelope({"status": 3, "video_Url": "https://tmp.example/v.mp4", "duration": 32}),
    )
    transport.on("GET", "https://tmp.example/v.mp4", b"MP4BYTES")

    from datetime import datetime

    from app.storage import StoredObject

    class FakeResultStorage:
        def put_object(self, key: str, content: bytes, *, content_type: str):
            return StoredObject(
                provider="fake",
                bucket="assets",
                key=key,
                uri=f"fake://assets/{key}",
                size=len(content),
                content_type=content_type,
                sha256="hash-" + str(len(content)),
                updated_at=datetime.now(tz=UTC),
            )

    storage = FakeResultStorage()
    monkeypatch.setattr("app.oral.get_media_storage", lambda _conn: storage)
    conn.execute(
        "UPDATE oral_tasks SET next_poll_at = '2000-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()

    assert run_next_oral_task(conn, worker_id="worker-1", vendor=vendor) == created.task_id
    refreshed = conn.execute(
        "SELECT * FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert refreshed["status"] == "SUCCEEDED"
    assert refreshed["result_asset_id"]
    assert refreshed["duration_sec"] == 32
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert tuple(wallet) == (9, 0)
    assert [
        row["type"]
        for row in conn.execute(
            "SELECT type FROM wallet_transactions WHERE oral_task_id = %s "
            "ORDER BY created_at, type",
            (created.task_id,),
        ).fetchall()
    ] == ["RESERVE", "SETTLE"]

    asset = conn.execute(
        "SELECT kind, project_id FROM assets WHERE id = ?", (refreshed["result_asset_id"],)
    ).fetchone()
    assert asset["kind"] == "oral_video"
    assert asset["project_id"] == "project-1"


def test_vendor_failure_lands_customer_safe_message(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-fail.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/video/create_by_tts",
        json.dumps({"code": 1002, "msg": "credit", "data": {}}).encode(),
    )

    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="t",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="idem-key-0004",
        vendor=vendor,
    )
    assert created.status == "QUEUED"
    assert run_next_oral_task(conn, worker_id="worker-1", vendor=vendor) == created.task_id
    refreshed = conn.execute(
        "SELECT * FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert refreshed["status"] == "FAILED"
    row = conn.execute(
        "SELECT error_message FROM oral_tasks WHERE id = ?", (created.task_id,)
    ).fetchone()
    assert row["error_message"] is not None
    assert "飞影" not in row["error_message"]
    assert "hifly" not in row["error_message"].lower()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert tuple(wallet) == (10, 0)


def test_transport_uncertainty_keeps_reservation_for_reconciliation(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    from app.hifly import HiflyError

    conn = seed_scene(tmp_path, "oral-uncertain.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()

    def uncertain(_body):
        raise HiflyError("数字人服务网络异常，请稍后重试")

    transport.on("POST", "/api/v2/hifly/video/create_by_tts", uncertain)
    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="t",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="idem-key-uncertain",
        vendor=vendor,
    )

    assert run_next_oral_task(conn, worker_id="worker-1", vendor=vendor) == created.task_id
    refreshed = conn.execute(
        "SELECT * FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()

    assert refreshed["status"] == "SUBMISSION_UNCERTAIN"
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert tuple(wallet) == (9, 1)

    from app.oral import reconcile_uncertain_oral_task

    resolved = reconcile_uncertain_oral_task(conn, task_id=created.task_id, outcome="RELEASE")
    assert resolved["status"] == "CANCELLED"
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert tuple(wallet) == (10, 0)


def test_http_status_during_submit_remains_uncertain_and_reserved(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    from app.hifly import HiflyError

    conn = seed_scene(tmp_path, "oral-http-uncertain.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()

    def gateway_timeout(_body):
        raise HiflyError("数字人服务返回 HTTP 504", vendor_code=504)

    transport.on("POST", "/api/v2/hifly/video/create_by_tts", gateway_timeout)
    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="t",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="idem-http-uncertain",
    )
    run_next_oral_task(conn, worker_id="worker-1", vendor=vendor)
    task = conn.execute(
        "SELECT status FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert task["status"] == "SUBMISSION_UNCERTAIN"
    assert tuple(wallet) == (9, 1)


def test_old_oral_lease_token_cannot_finalize_or_release_wallet(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-stale-token.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="t",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="idem-stale-token",
    )
    from app.oral import acquire_oral_task, prepare_oral_task_work

    vendor, _ = make_vendor()
    lease = acquire_oral_task(conn, worker_id="reused-worker")
    assert lease is not None
    work = prepare_oral_task_work(conn, lease=lease, vendor=vendor)
    conn.execute(
        "UPDATE oral_tasks SET lease_token = %s WHERE id = %s",
        ("replacement-token", created.task_id),
    )
    conn.commit()
    with pytest.raises(OralDomainError, match="租约"):
        finalize_oral_task_work(conn, work=work, outcome=OralOutcome(status="FAILED"))
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(wallet) == (9, 1)


def test_old_clone_lease_token_cannot_overwrite_new_claim(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "clone-stale-token.db")
    started = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="avatar-stale-token",
    )
    from app.oral import acquire_oral_clone, prepare_oral_clone_work

    vendor, _ = make_vendor()
    lease = acquire_oral_clone(conn, worker_id="reused-worker")
    assert lease is not None
    work = prepare_oral_clone_work(conn, lease=lease, vendor=vendor)
    conn.execute(
        "UPDATE oral_avatars SET lease_token = %s WHERE id = %s",
        ("replacement-token", started.task_id),
    )
    conn.commit()
    with pytest.raises(OralDomainError, match="租约"):
        finalize_oral_clone_work(conn, work=work, outcome=CloneOutcome(status="RUNNING"))


def test_clone_requires_consent_bound_to_same_identity(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "clone-consent-binding.db")
    conn.execute(
        "INSERT INTO assets (id, kind, storage_uri, sha256, size_bytes, content_type, "
        "created_by_user_id) VALUES ('other-consent', 'identity_authorization', "
        "'local://assets/other.jpg', '', 0, 'image/jpeg', 'employee_1')"
    )
    conn.commit()
    with pytest.raises(OralDomainError, match="当前人物不匹配"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="分身",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="other-consent",
            idempotency_key="wrong-consent",
        )


def test_clone_consent_rejects_unrelated_owned_asset_and_accepts_exact_binding(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "clone-consent-source-binding.db")
    conn.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES (%s, 'project-1', 'source_video', "
        "'local://assets/unrelated.mp4', %s, 0, 'video/mp4', 'employee_1')",
        ("unrelated-video", "c" * 64),
    )
    conn.commit()

    with pytest.raises(OralDomainError, match="未绑定当前克隆素材"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="错误素材",
            source_asset_id="unrelated-video",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="unrelated-owned-source",
        )

    accepted = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="正确素材",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="exact-consent-source",
    )
    assert accepted.status == "PENDING"


def test_clone_consent_binding_is_persisted_with_source_fingerprint(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "clone-consent-persist.db")
    conn.execute(
        "UPDATE assets SET metadata_json = %s WHERE id = 'asset-auth'",
        (json.dumps({"identity_id": "ident-1", "purpose": "authorization"}),),
    )
    conn.commit()

    result = record_oral_clone_consent(
        conn,
        actor=actor(),
        identity_id="ident-1",
        source_asset_id="asset-src",
        purpose="oral_avatar_clone",
    )

    assert result["source_sha256"] == "a" * 64
    metadata = json.loads(
        conn.execute("SELECT metadata_json FROM assets WHERE id = 'asset-auth'").fetchone()[0]
    )
    assert metadata["oral_clone_consents"] == [
        {
            "identity_id": "ident-1",
            "source_asset_id": "asset-src",
            "source_sha256": "a" * 64,
            "purpose": "oral_avatar_clone",
        }
    ]


def test_oral_finalize_db_failure_preserves_outcome_and_wallet_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import generation_worker

    conn = seed_scene(tmp_path, "oral-finalize-db-failure.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    created = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="待对账口播",
        script_text="测试文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="finalize-db-failure",
    )
    lease = acquire_oral_task(conn, worker_id="worker-finalize-failure")
    assert lease is not None
    outcome = OralOutcome(status="RUNNING", vendor_task_id="vendor-video-accepted")

    @contextmanager
    def fake_pg_transaction():
        yield object()

    monkeypatch.setattr(generation_worker, "pg_transaction", fake_pg_transaction)
    monkeypatch.setattr(
        generation_worker.BusinessConnection,
        "postgres",
        staticmethod(lambda _raw: conn),
    )
    monkeypatch.setattr(
        generation_worker,
        "finalize_oral_task_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database write failed")),
    )

    generation_worker._finalize_pg_oral_task_after_external(
        lease=lease, work=object(), outcome=outcome
    )

    task = conn.execute(
        "SELECT status, vendor_task_id, reconciliation_json FROM oral_tasks WHERE id = %s",
        (created.task_id,),
    ).fetchone()
    assert task["status"] == "SUBMISSION_UNCERTAIN"
    assert task["vendor_task_id"] == "vendor-video-accepted"
    assert json.loads(task["reconciliation_json"])["status"] == "RUNNING"
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(wallet) == (9, 1)
    assert (
        conn.execute(
            "SELECT count(*) FROM wallet_transactions WHERE oral_task_id = %s "
            "AND type IN ('SETTLE', 'RELEASE')",
            (created.task_id,),
        ).fetchone()[0]
        == 0
    )


def test_clone_finalize_db_failure_preserves_vendor_association(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import generation_worker

    conn = seed_scene(tmp_path, "clone-finalize-db-failure.db")
    created = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="待对账分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="clone-finalize-db-failure",
    )
    lease = acquire_oral_clone(conn, worker_id="worker-clone-finalize-failure")
    assert lease is not None
    outcome = CloneOutcome(status="RUNNING", vendor_task_id="vendor-clone-accepted")

    @contextmanager
    def fake_pg_transaction():
        yield object()

    monkeypatch.setattr(generation_worker, "pg_transaction", fake_pg_transaction)
    monkeypatch.setattr(
        generation_worker.BusinessConnection,
        "postgres",
        staticmethod(lambda _raw: conn),
    )
    monkeypatch.setattr(
        generation_worker,
        "finalize_oral_clone_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database write failed")),
    )

    generation_worker._finalize_pg_oral_clone_after_external(
        lease=lease, work=object(), outcome=outcome
    )

    clone = conn.execute(
        "SELECT status, vendor_task_id, reconciliation_json FROM oral_avatars WHERE id = %s",
        (created.task_id,),
    ).fetchone()
    assert clone["status"] == "SUBMISSION_UNCERTAIN"
    assert clone["vendor_task_id"] == "vendor-clone-accepted"
    assert json.loads(clone["reconciliation_json"])["status"] == "RUNNING"


def test_clone_idempotency_is_owner_scoped_and_payload_bound(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "clone-idempotency.db")
    first = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="avatar-idempotency-1",
    )
    replay = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="avatar-idempotency-1",
    )
    assert replay.task_id == first.task_id
    with pytest.raises(OralDomainError, match="不同"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="另一分身",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-idempotency-1",
        )


def test_voice_requires_archived_demo_and_explicit_confirmation(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "voice-confirm.db")
    conn.execute(
        "INSERT INTO oral_voices (id, identity_id, owner_user_id, title, vendor_voice_id, "
        "status, source_asset_id, demo_asset_id, confirmed) VALUES "
        "('voice-demo', 'ident-1', 'employee_1', '声音', 'vendor-v', 'READY', "
        "'asset-audio', 'demo-asset', 0)"
    )
    conn.commit()
    confirmed = confirm_voice_clone(conn, voice_id="voice-demo", actor=actor())
    assert confirmed["confirmed"] == 1


def test_oral_sources_require_owner_current_authorization_and_non_auditor(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-permissions.db")
    vendor, _ = make_vendor()
    conn.execute(
        "INSERT INTO users (id, username, display_name, role) "
        "VALUES ('employee_2', 'employee_2', 'Employee Two', 'employee')"
    )
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES ('project-2', 'employee_2', 'P2')"
    )
    conn.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES "
        "('foreign-video', 'project-2', 'source_video', 'local://assets/foreign.mp4', "
        "'', 0, 'video/mp4', 'employee_2')"
    )
    conn.commit()

    with pytest.raises(OralDomainError, match="无权"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="foreign",
            source_asset_id="foreign-video",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="foreign-avatar-1",
            vendor=vendor,
        )
    with pytest.raises(OralDomainError, match="审计"):
        start_avatar_clone(
            conn,
            actor=auditor(),
            identity_id="ident-1",
            title="audit",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="auditor-avatar-1",
            vendor=vendor,
        )
    conn.execute(
        "UPDATE person_identities SET authorization_expires_at = "
        "'2020-01-01T00:00:00+00:00' WHERE id = 'ident-1'"
    )
    with pytest.raises(OralDomainError, match="授权"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="expired",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="expired-avatar-1",
            vendor=vendor,
        )


def test_oral_unit_price_defaults_and_reads_settings(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-price.db")
    assert oral_unit_price_fen(conn) == ORAL_UNIT_PRICE_FEN_DEFAULT == 1000


def test_oral_unit_price_fails_closed_when_settings_are_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = seed_scene(tmp_path, "oral-price-failed.db")
    monkeypatch.setattr(
        "app.oral.SettingsRepository.read_billing_settings",
        lambda _self: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    with pytest.raises(OralDomainError, match="计费配置暂不可用"):
        oral_unit_price_fen(conn)
