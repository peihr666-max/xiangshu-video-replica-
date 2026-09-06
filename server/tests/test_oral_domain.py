"""Oral digital-human domain tests (C1 slice ②).

Vendor transport is scripted; storage is stubbed at the module seam
(``app.oral.storage_for_asset`` / ``app.oral.get_media_storage``) so these
tests exercise clone flows, task lifecycle, idempotency, and pricing without
network or real buckets.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user, get_database
from app.customer_fence import get_business_db
from app.db import initialize_database
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyError
from app.internal_billing import BillingInvariantError, finalize_oral_billing
from app.main import app
from app.oral import (
    ORAL_CONSENT_TEXT_VERSION,
    ORAL_UNIT_PRICE_FEN_DEFAULT,
    OralConflictError,
    OralDomainError,
    cancel_oral_task,
    confirm_voice_clone,
    create_oral_consent,
    create_oral_task,
    list_oral_consents,
    oral_unit_price_fen,
    refresh_oral_task,
    start_avatar_clone,
    start_voice_clone,
)
from app.oral_routes import get_oral_vendor
from app.oral_worker import (
    claim_oral_work,
    finalize_oral_work,
    perform_oral_work,
    prepare_oral_work,
)
from app.storage import StoredObject

_NOW = "2026-09-06 03:00:00"


class FakeSourceStorage:
    def __init__(self, payload: bytes = b"FAKEMEDIA") -> None:
        self.payload = payload
        self.objects: dict[str, bytes] = {}

    def get_object(self, key: str) -> bytes:
        return self.objects.get(key, self.payload)

    def put_object(self, key: str, content: bytes, *, content_type: str) -> StoredObject:
        self.objects[key] = content
        return StoredObject(
            provider="fake",
            bucket="assets",
            key=key,
            uri=f"fake://assets/{key}",
            size=len(content),
            content_type=content_type,
            sha256=f"sha-{key}",
            updated_at=datetime.now(tz=UTC),
        )

    def delete_object(self, key: str, *, actor_id: str | None = None) -> None:
        self.objects.pop(key, None)


def run_oral_worker_step(
    conn: BusinessConnection,
    *,
    vendor: HiflyClient,
    storage: FakeSourceStorage,
    worker_id: str = "oral-test-worker",
):
    lease = claim_oral_work(conn, worker_id=worker_id)
    if lease is None:
        return None
    prepared = prepare_oral_work(conn, lease)
    result = perform_oral_work(prepared, vendor=vendor, storage=storage)
    finalize_oral_work(conn, lease=prepared, result=result)
    return result


@pytest.fixture()
def fake_source_storage(monkeypatch: pytest.MonkeyPatch) -> FakeSourceStorage:
    storage = FakeSourceStorage()
    monkeypatch.setattr("app.oral.storage_for_asset", lambda _conn, _uri: storage)
    return storage


def actor(user_id: str = "employee_1", role: str = "employee") -> CurrentUser:
    return CurrentUser(id=user_id, username=user_id, display_name=user_id, role=role)


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
        "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
        ("employee_2", "employee_2", "Other Employee", "employee"),
    )
    connection.execute(
        "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
        ("admin_1", "admin_1", "Administrator", "admin"),
    )
    connection.execute(
        "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
        ("auditor_1", "auditor_1", "Auditor", "auditor"),
    )
    connection.executemany(
        "INSERT INTO wallets (user_id, available_credits, reserved_credits) VALUES (?, ?, 0)",
        [("employee_1", 20), ("employee_2", 20)],
    )
    connection.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
        ("oral-project", "employee_1", "Oral Project"),
    )
    connection.execute(
        """
        INSERT INTO person_identities (id, owner_user_id, display_name, status)
        VALUES ('ident-1', 'employee_1', '张工', 'ACTIVE')
        """
    )
    connection.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        )
        VALUES (
            'asset-src', 'oral-project', 'source_video', 'local://assets/src.mp4',
            'video-hash', 9, 'video/mp4', 'employee_1'
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
            'asset-image', 'oral-project', 'character_source_image',
            'local://assets/src.png', 'image-hash', 9, 'image/png', 'employee_1'
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
            'asset-audio', NULL, 'oral_audio', 'local://assets/v.mp3',
            'audio-hash', 9, 'audio/mpeg', 'employee_1'
        )
        """
    )
    connection.commit()
    return BusinessConnection.sqlite(connection)


def seed_ready_assets(conn: BusinessConnection) -> tuple[str, str]:
    avatar_consent = consent_for(conn, purpose="AVATAR_CLONE", source_asset_id="asset-src")
    voice_consent = consent_for(conn, purpose="VOICE_CLONE", source_asset_id="asset-audio")
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (
            'voice-demo-ready', NULL, 'oral_audio', 'local://assets/demo.mp3',
            'demo-hash', 9, 'audio/mpeg', 'employee_1'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO oral_avatars (
            id, identity_id, owner_user_id, title, vendor_avatar_id,
            status, source_kind, source_asset_id, consent_id
        )
        VALUES (
            'avatar-ready', 'ident-1', 'employee_1', '张工分身',
            'vendor-avatar-9', 'READY', 'VIDEO', 'asset-src', %s
        )
        """,
        (avatar_consent,),
    )
    conn.execute(
        """
        INSERT INTO oral_voices (
            id, identity_id, owner_user_id, title, vendor_voice_id,
            status, source_asset_id, consent_id, confirmed, demo_asset_id
        )
        VALUES (
            'voice-ready', 'ident-1', 'employee_1', '张工声音',
            'vendor-voice-9', 'READY', 'asset-audio', %s, 1, 'voice-demo-ready'
        )
        """,
        (voice_consent,),
    )
    conn.commit()
    return "avatar-ready", "voice-ready"


def consent_for(
    conn: BusinessConnection,
    *,
    purpose: str,
    source_asset_id: str,
) -> str:
    return str(
        create_oral_consent(
            conn,
            actor=actor(),
            identity_id="ident-1",
            source_asset_id=source_asset_id,
            purpose=purpose,
            consent_text_version=ORAL_CONSENT_TEXT_VERSION,
        )["id"]
    )


def test_create_and_list_consent_snapshots_source_and_audits(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-consent.db")

    created = create_oral_consent(
        conn,
        actor=actor(),
        identity_id="ident-1",
        source_asset_id="asset-audio",
        purpose="VOICE_CLONE",
        consent_text_version=ORAL_CONSENT_TEXT_VERSION,
    )

    assert created["owner_user_id"] == "employee_1"
    assert created["source_sha256"] == "audio-hash"
    assert created["purpose"] == "VOICE_CLONE"
    assert created["consented_at"]
    assert list_oral_consents(conn, actor=actor(), identity_id="ident-1") == [created]
    audit = conn.execute(
        "SELECT action, entity_id, metadata_json FROM audit_logs WHERE entity_id = %s",
        (created["id"],),
    ).fetchone()
    assert audit is not None
    assert audit["action"] == "oral.consent.create"
    assert json.loads(str(audit["metadata_json"])) == {
        "consent_text_version": ORAL_CONSENT_TEXT_VERSION,
        "identity_id": "ident-1",
        "purpose": "VOICE_CLONE",
        "source_asset_id": "asset-audio",
        "source_sha256": "audio-hash",
    }


def test_consent_read_keeps_foreign_and_missing_identity_indistinguishable(
    tmp_path: Path,
) -> None:
    conn = seed_scene(tmp_path, "oral-consent-permission.db")

    with pytest.raises(OralDomainError) as foreign:
        list_oral_consents(conn, actor=actor("employee_2"), identity_id="ident-1")
    with pytest.raises(OralDomainError) as missing:
        list_oral_consents(conn, actor=actor("employee_2"), identity_id="missing")

    assert str(foreign.value) == str(missing.value)


def test_consent_and_voice_confirmation_routes(
    tmp_path: Path,
) -> None:
    conn = seed_scene(tmp_path, "oral-consent-routes.db")
    vendor, _ = make_vendor()

    class TestBusinessDb:
        @contextmanager
        def write(self) -> Iterator[tuple[BusinessConnection, CurrentUser]]:
            yield conn, actor()

    def database_override() -> Iterator[BusinessConnection]:
        yield conn

    app.dependency_overrides[get_database] = database_override
    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[get_business_db] = TestBusinessDb
    app.dependency_overrides[get_oral_vendor] = lambda: vendor
    try:
        client = TestClient(app)
        created = client.post(
            "/api/oral/consents",
            json={
                "identity_id": "ident-1",
                "source_asset_id": "asset-audio",
                "purpose": "VOICE",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["purpose"] == "VOICE_CLONE"

        listed = client.get("/api/oral/consents", params={"identity_id": "ident-1"})
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()] == [created.json()["id"]]

        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256, size_bytes,
                content_type, created_by_user_id
            ) VALUES ('voice-route-demo', NULL, 'oral_audio',
                      'local://assets/route-demo.mp3', 'route-demo-hash', 9,
                      'audio/mpeg', 'employee_1')
            """
        )
        conn.execute(
            """
            INSERT INTO oral_voices (
                id, identity_id, owner_user_id, title, vendor_voice_id,
                status, source_asset_id, consent_id, confirmed, demo_asset_id
            ) VALUES (%s, 'ident-1', 'employee_1', '待确认声音', 'vendor-voice',
                      'READY', 'asset-audio', %s, 0, 'voice-route-demo')
            """,
            ("voice-route", created.json()["id"]),
        )
        conn.commit()
        confirmed = client.post("/api/oral/voices/voice-route/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["confirmed"] == 1
        assert confirmed.json()["confirmed_by_user_id"] == "employee_1"
    finally:
        app.dependency_overrides.clear()


def test_clone_route_only_enqueues_before_returning_202(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-clone-route-uncertain.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/avatar",
                "content_type": "video/mp4",
                "file_id": "file-avatar",
            }
        ),
    )

    def uncertain(_body: bytes | None) -> bytes:
        raise HiflyError("连接中断")

    transport.on("POST", "/api/v2/hifly/avatar/create_by_video", uncertain)

    class TestBusinessDb:
        @contextmanager
        def write(self) -> Iterator[tuple[BusinessConnection, CurrentUser]]:
            yield conn, actor()

    app.dependency_overrides[get_business_db] = TestBusinessDb
    app.dependency_overrides[get_oral_vendor] = lambda: vendor
    try:
        client = TestClient(app)
        consent = client.post(
            "/api/oral/consents",
            json={
                "identity_id": "ident-1",
                "source_asset_id": "asset-src",
                "purpose": "AVATAR",
            },
        )
        response = client.post(
            "/api/oral/avatars",
            json={
                "identity_id": "ident-1",
                "title": "张工分身",
                "source_asset_id": "asset-src",
                "source_kind": "VIDEO",
                "consent_id": consent.json()["id"],
                "idempotency_key": "route-uncertain-key",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert transport.calls == []
    persisted = conn.execute(
        "SELECT submission_state FROM oral_avatars WHERE idempotency_key = %s",
        ("route-uncertain-key",),
    ).fetchone()
    assert persisted["submission_state"] == "LOCAL_PENDING"


def test_oral_task_route_returns_202_without_vendor_and_cancel_is_idempotent(
    tmp_path: Path,
) -> None:
    conn = seed_scene(tmp_path, "oral-task-route-queue.db")
    avatar_id, voice_id = seed_ready_assets(conn)

    class TestBusinessDb:
        @contextmanager
        def write(self) -> Iterator[tuple[BusinessConnection, CurrentUser]]:
            yield conn, actor()

    app.dependency_overrides[get_business_db] = TestBusinessDb
    try:
        client = TestClient(app)
        response = client.post(
            "/api/oral/tasks",
            json={
                "identity_id": "ident-1",
                "avatar_id": avatar_id,
                "voice_id": voice_id,
                "mode": "TTS",
                "title": "排队口播",
                "script_text": "文案",
                "audio_asset_id": None,
                "subtitle": None,
                "idempotency_key": "route-queue-key",
            },
        )
        first_cancel = client.post(f"/api/oral/tasks/{response.json()['id']}/cancel")
        replay_cancel = client.post(f"/api/oral/tasks/{response.json()['id']}/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert first_cancel.status_code == replay_cancel.status_code == 200
    assert first_cancel.json()["status"] == replay_cancel.json()["status"] == "CANCELLED"
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert (wallet["available_credits"], wallet["reserved_credits"]) == (20, 0)


def test_avatar_clone_start_then_refresh_to_ready(
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
        consent_id=consent_for(conn, purpose="AVATAR_CLONE", source_asset_id="asset-src"),
        idempotency_key="avatar-clone-idem-1",
        vendor=vendor,
    )
    assert started.status == "PENDING"
    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    conn.execute("UPDATE oral_avatars SET next_attempt_at = NULL WHERE id = %s", (started.task_id,))
    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    refreshed = conn.execute(
        "SELECT * FROM oral_avatars WHERE id = %s", (started.task_id,)
    ).fetchone()
    assert refreshed["status"] == "READY"
    assert refreshed["vendor_avatar_id"] == "vendor-avatar-1"
    # 上传走 PUT；创建与查询各一次 POST/GET。
    assert any(method == "PUT" for method, _ in transport.calls)


def test_avatar_clone_from_image_uses_image_provider_endpoint(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-avatar-image.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/image",
                "content_type": "image/png",
                "file_id": "file-image",
            }
        ),
    )
    transport.on(
        "POST",
        "/api/v2/hifly/avatar/create_by_image",
        envelope({"task_id": "image-task-1"}),
    )

    started = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="张工照片分身",
        source_asset_id="asset-image",
        source_kind="IMAGE",
        consent_id=consent_for(conn, purpose="AVATAR_CLONE", source_asset_id="asset-image"),
        idempotency_key="avatar-image-idem-1",
        vendor=vendor,
    )

    assert started.status == "PENDING"
    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    assert any(url.endswith("/avatar/create_by_image") for _, url in transport.calls)
    assert not any(url.endswith("/avatar/create_by_video") for _, url in transport.calls)


@pytest.mark.parametrize(
    ("operation", "asset_id", "source_kind", "message"),
    [
        ("avatar", "asset-audio", "VIDEO", "素材类型"),
        ("avatar", "asset-src", "IMAGE", "素材类型"),
        ("voice", "asset-src", None, "音频素材"),
    ],
)
def test_clone_rejects_wrong_media_type(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    operation: str,
    asset_id: str,
    source_kind: str | None,
    message: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-wrong-type-{operation}-{source_kind}.db")
    vendor, _ = make_vendor()

    with pytest.raises(OralDomainError, match=message):
        if operation == "avatar":
            start_avatar_clone(
                conn,
                actor=actor(),
                identity_id="ident-1",
                title="错误素材",
                source_asset_id=asset_id,
                source_kind=str(source_kind),
                consent_id=consent_for(conn, purpose="AVATAR_CLONE", source_asset_id=asset_id),
                idempotency_key=f"wrong-avatar-{asset_id}-{source_kind}",
                vendor=vendor,
            )
        else:
            start_voice_clone(
                conn,
                actor=actor(),
                identity_id="ident-1",
                title="错误素材",
                source_asset_id=asset_id,
                consent_id=consent_for(conn, purpose="VOICE_CLONE", source_asset_id=asset_id),
                idempotency_key=f"wrong-voice-{asset_id}",
                vendor=vendor,
            )


def test_clone_rejects_inaccessible_and_incomplete_assets(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-inaccessible-assets.db")
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
        ("other-project", "employee_2", "Other Project"),
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "other-video",
            "other-project",
            "source_video",
            "local://assets/other.mp4",
            "other-hash",
            9,
            "video/mp4",
            "employee_2",
        ),
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "other-audio",
            "other-project",
            "oral_audio",
            "local://assets/other.mp3",
            "other-audio-hash",
            9,
            "audio/mpeg",
            "employee_2",
        ),
    )
    conn.execute("UPDATE assets SET sha256 = '', size_bytes = 0 WHERE id = 'asset-audio'")
    conn.commit()
    vendor, _ = make_vendor()

    with pytest.raises(HTTPException) as inaccessible:
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="他人素材",
            source_asset_id="other-video",
            source_kind="VIDEO",
            consent_id="consent-hidden",
            idempotency_key="hidden-avatar-key",
            vendor=vendor,
        )
    assert inaccessible.value.status_code == 404
    with pytest.raises(HTTPException) as inaccessible_audio:
        start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="他人音频",
            source_asset_id="other-audio",
            consent_id="consent-hidden",
            idempotency_key="hidden-voice-key",
            vendor=vendor,
        )
    assert inaccessible_audio.value.status_code == 404
    with pytest.raises(OralDomainError, match="音频素材.*失效"):
        start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="未完成素材",
            source_asset_id="asset-audio",
            consent_id="consent-hidden",
            idempotency_key="incomplete-voice-key",
            vendor=vendor,
        )


@pytest.mark.parametrize("role", ["admin", "auditor"])
def test_privileged_roles_cannot_clone_another_users_biometric_asset(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    role: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-biometric-owner-{role}.db")
    user_id = f"{role}_1"
    privileged = actor(user_id, role)
    conn.execute(
        """
        INSERT INTO person_identities (id, owner_user_id, display_name, status)
        VALUES (%s, %s, '特权用户人物', 'ACTIVE')
        """,
        (f"ident-{role}", user_id),
    )
    conn.commit()
    vendor, transport = make_vendor()

    with pytest.raises(HTTPException) as hidden:
        start_avatar_clone(
            conn,
            actor=privileged,
            identity_id=f"ident-{role}",
            title="他人素材",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="not-reachable",
            idempotency_key=f"privileged-{role}-clone",
            vendor=vendor,
        )

    assert hidden.value.status_code == 404
    assert transport.calls == []


def test_clone_rejects_consent_mismatch_before_vendor_call(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-consent-mismatch.db")
    vendor, transport = make_vendor()
    voice_consent = consent_for(conn, purpose="VOICE_CLONE", source_asset_id="asset-audio")
    avatar_consent = consent_for(conn, purpose="AVATAR_CLONE", source_asset_id="asset-src")
    conn.execute(
        """
        INSERT INTO person_identities (id, owner_user_id, display_name, status)
        VALUES ('ident-owned-2', 'employee_1', '同用户其他人物', 'ACTIVE'),
               ('ident-foreign', 'employee_2', '其他用户人物', 'ACTIVE')
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES ('asset-foreign-audio', NULL, 'oral_audio',
                  'local://assets/foreign.mp3', 'foreign-audio-hash', 9,
                  'audio/mpeg', 'employee_2')
        """
    )
    identity_mismatch = create_oral_consent(
        conn,
        actor=actor(),
        identity_id="ident-owned-2",
        source_asset_id="asset-src",
        purpose="AVATAR_CLONE",
        consent_text_version=ORAL_CONSENT_TEXT_VERSION,
    )["id"]
    owner_mismatch = create_oral_consent(
        conn,
        actor=actor("employee_2"),
        identity_id="ident-foreign",
        source_asset_id="asset-foreign-audio",
        purpose="VOICE_CLONE",
        consent_text_version=ORAL_CONSENT_TEXT_VERSION,
    )["id"]

    for consent_id, source_asset_id in [
        (voice_consent, "asset-src"),
        (avatar_consent, "asset-image"),
        ("missing-consent", "asset-src"),
    ]:
        with pytest.raises(OralDomainError, match="授权"):
            start_avatar_clone(
                conn,
                actor=actor(),
                identity_id="ident-1",
                title="无效授权",
                source_asset_id=source_asset_id,
                source_kind="VIDEO" if source_asset_id == "asset-src" else "IMAGE",
                consent_id=consent_id,
                idempotency_key=f"mismatch-avatar-{consent_id}",
                vendor=vendor,
            )
    with pytest.raises(OralDomainError, match="授权"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="身份不匹配",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id=str(identity_mismatch),
            idempotency_key="identity-mismatch-key",
            vendor=vendor,
        )
    with pytest.raises(OralDomainError, match="授权"):
        start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="用户不匹配",
            source_asset_id="asset-audio",
            consent_id=str(owner_mismatch),
            idempotency_key="owner-mismatch-key",
            vendor=vendor,
        )
    conn.execute("UPDATE assets SET sha256 = 'changed-hash' WHERE id = 'asset-src'")
    with pytest.raises(OralDomainError, match="授权"):
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="素材内容已变化",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id=avatar_consent,
            idempotency_key="hash-mismatch-key",
            vendor=vendor,
        )
    assert transport.calls == []


def test_voice_clone_ready_requires_explicit_confirmation(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
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
            {
                "status": 3,
                "voice": "vendor-voice-2",
                "demo_url": "https://tmp.example/voice-demo.mp3",
            }
        ),
    )
    transport.on("GET", "https://tmp.example/voice-demo.mp3", b"MP3DEMO")

    started = start_voice_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="张工声音",
        source_asset_id="asset-audio",
        consent_id=consent_for(conn, purpose="VOICE_CLONE", source_asset_id="asset-audio"),
        idempotency_key="voice-clone-idem-1",
        vendor=vendor,
    )
    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    conn.execute("UPDATE oral_voices SET next_attempt_at = NULL WHERE id = %s", (started.task_id,))
    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    refreshed = conn.execute(
        "SELECT * FROM oral_voices WHERE id = %s", (started.task_id,)
    ).fetchone()
    assert refreshed["status"] == "READY"
    assert refreshed["vendor_voice_id"] == "vendor-voice-2"
    assert refreshed["confirmed"] == 0
    assert refreshed["confirmed_by_user_id"] is None
    assert refreshed["confirmed_at"] is None

    confirmed = confirm_voice_clone(conn, voice_id=started.task_id, actor=actor())
    assert confirmed["confirmed"] == 1
    assert confirmed["confirmed_by_user_id"] == "employee_1"
    assert confirmed["confirmed_at"]
    audit = conn.execute(
        "SELECT action FROM audit_logs WHERE entity_id = %s", (started.task_id,)
    ).fetchone()
    assert audit is not None
    assert audit["action"] == "oral.voice.confirm"


def test_voice_clone_done_without_demo_stays_running(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-voice-no-demo.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/voice",
                "content_type": "audio/mpeg",
                "file_id": "file-voice",
            }
        ),
    )
    transport.on("POST", "/api/v2/hifly/voice/create", envelope({"task_id": "voice-task"}))
    transport.on(
        "GET",
        "/api/v2/hifly/voice/task",
        envelope({"status": 3, "voice": "vendor-voice", "demo_url": ""}),
    )
    started = start_voice_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="缺试听",
        source_asset_id="asset-audio",
        consent_id=consent_for(conn, purpose="VOICE", source_asset_id="asset-audio"),
        idempotency_key="voice-no-demo-key",
        vendor=vendor,
    )

    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    conn.execute("UPDATE oral_voices SET next_attempt_at = NULL WHERE id = %s", (started.task_id,))
    assert run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage) is not None
    refreshed = conn.execute(
        "SELECT * FROM oral_voices WHERE id = %s", (started.task_id,)
    ).fetchone()

    assert refreshed["status"] == "RUNNING"
    assert refreshed["demo_asset_id"] is None


def test_clone_submission_uncertain_is_persisted_and_not_retried(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-avatar-uncertain.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/avatar",
                "content_type": "video/mp4",
                "file_id": "file-avatar",
            }
        ),
    )

    def uncertain(_body: bytes | None) -> bytes:
        raise HiflyError("连接中断")

    transport.on("POST", "/api/v2/hifly/avatar/create_by_video", uncertain)
    consent_id = consent_for(conn, purpose="AVATAR", source_asset_id="asset-src")

    started = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="提交不确定",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id=consent_id,
        idempotency_key="avatar-uncertain-key",
        vendor=vendor,
    )
    result = run_oral_worker_step(conn, vendor=vendor, storage=fake_source_storage)
    assert result is not None and result.outcome == "uncertain"
    persisted = conn.execute(
        "SELECT id, status, submission_state FROM oral_avatars WHERE idempotency_key = %s",
        ("avatar-uncertain-key",),
    ).fetchone()
    assert persisted["status"] == "PENDING"
    assert persisted["submission_state"] == "SUBMISSION_UNKNOWN"
    assert started.task_id == persisted["id"]
    assert claim_oral_work(conn, worker_id="second-worker") is None

    replayed = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="提交不确定",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id=consent_id,
        idempotency_key="avatar-uncertain-key",
        vendor=vendor,
    )
    assert replayed.task_id == persisted["id"]
    assert replayed.submission_state == "SUBMISSION_UNKNOWN"
    assert replayed.replayed is True
    assert sum(1 for method, url in transport.calls if url.endswith("/avatar/create_by_video")) == 1


def test_voice_confirm_rejects_unready_and_foreign_as_missing(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-voice-confirm-guard.db")
    conn.execute(
        """
        INSERT INTO oral_voices (
            id, identity_id, owner_user_id, title, status, source_asset_id
        ) VALUES ('voice-running', 'ident-1', 'employee_1', '未完成声音', 'RUNNING', 'asset-audio')
        """
    )

    with pytest.raises(OralDomainError, match="就绪"):
        confirm_voice_clone(conn, voice_id="voice-running", actor=actor())
    with pytest.raises(OralDomainError) as foreign:
        confirm_voice_clone(conn, voice_id="voice-running", actor=actor("employee_2"))
    with pytest.raises(OralDomainError) as missing:
        confirm_voice_clone(conn, voice_id="missing", actor=actor("employee_2"))
    assert str(foreign.value) == str(missing.value)


def test_create_oral_task_tts_queues_reserves_and_replays_idempotently(
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
    assert not transport.calls
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert (wallet["available_credits"], wallet["reserved_credits"]) == (19, 1)
    reserve = conn.execute(
        """
        SELECT task_id, oral_task_id, type FROM wallet_transactions
        WHERE oral_task_id = %s
        """,
        (created.task_id,),
    ).fetchone()
    assert dict(reserve) == {
        "task_id": None,
        "oral_task_id": created.task_id,
        "type": "RESERVE",
    }


def test_oral_task_same_owner_idempotency_key_rejects_changed_payload(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-task-idempotency-conflict.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    transport.on("POST", "/api/v2/hifly/video/create_by_tts", envelope({"task_id": "vt-1"}))
    common = {
        "actor": actor(),
        "identity_id": "ident-1",
        "avatar_id": avatar_id,
        "voice_id": voice_id,
        "mode": "TTS",
        "title": "乡墅口播",
        "audio_asset_id": None,
        "subtitle": None,
        "idempotency_key": "same-owner-key",
        "vendor": vendor,
    }
    create_oral_task(conn, script_text="版本一", **common)

    with pytest.raises(OralConflictError, match="幂等键"):
        create_oral_task(conn, script_text="版本二", **common)

    assert transport.calls == []


def test_oral_task_idempotency_key_is_scoped_by_owner(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-task-owner-idempotency.db")
    avatar_id, _ = seed_ready_assets(conn)
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
        ("oral-project-2", "employee_2", "Other Oral Project"),
    )
    conn.execute(
        """
        INSERT INTO person_identities (id, owner_user_id, display_name, status)
        VALUES ('ident-2', 'employee_2', '李工', 'ACTIVE')
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES
            ('asset-src-2', 'oral-project-2', 'source_video',
             'local://assets/src-2.mp4', 'video-hash-2', 9, 'video/mp4', 'employee_2'),
            ('asset-audio-2', 'oral-project-2', 'oral_audio',
             'local://assets/audio-2.mp3', 'audio-hash-2', 9, 'audio/mpeg', 'employee_2')
        """
    )
    avatar_consent = create_oral_consent(
        conn,
        actor=actor("employee_2"),
        identity_id="ident-2",
        source_asset_id="asset-src-2",
        purpose="AVATAR",
        consent_text_version=ORAL_CONSENT_TEXT_VERSION,
    )["id"]
    conn.execute(
        """
        INSERT INTO oral_avatars (
            id, identity_id, owner_user_id, title, vendor_avatar_id, status,
            source_kind, source_asset_id, consent_id
        ) VALUES ('avatar-ready-2', 'ident-2', 'employee_2', '李工分身',
                  'vendor-avatar-2', 'READY', 'VIDEO', 'asset-src-2', %s)
        """,
        (avatar_consent,),
    )
    conn.commit()
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/audio",
                "content_type": "audio/mpeg",
                "file_id": "file-audio",
            }
        ),
    )
    transport.on("POST", "/api/v2/hifly/video/create_by_audio", envelope({"task_id": "vt"}))

    first = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="用户一",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key="shared-owner-key",
        vendor=vendor,
    )
    second = create_oral_task(
        conn,
        actor=actor("employee_2"),
        identity_id="ident-2",
        avatar_id="avatar-ready-2",
        voice_id=None,
        mode="AUDIO",
        title="用户二",
        script_text=None,
        audio_asset_id="asset-audio-2",
        subtitle=None,
        idempotency_key="shared-owner-key",
        vendor=vendor,
    )

    assert first.task_id != second.task_id


@pytest.mark.parametrize("missing_consent", ["avatar", "voice"])
def test_historical_ready_clone_without_consent_cannot_create_oral_task(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    missing_consent: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-historical-{missing_consent}.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    conn.execute(f"UPDATE oral_{missing_consent}s SET consent_id = NULL")
    conn.commit()
    vendor, transport = make_vendor()

    with pytest.raises(OralDomainError, match="授权"):
        create_oral_task(
            conn,
            actor=actor(),
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=voice_id,
            mode="TTS",
            title="历史数据",
            script_text="文案",
            audio_asset_id=None,
            subtitle=None,
            idempotency_key=f"historical-{missing_consent}",
            vendor=vendor,
        )
    assert transport.calls == []


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


def test_oral_billing_cancel_releases_once_and_success_settles_once(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-billing-finalize.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, _ = make_vendor()

    cancelled = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="取消任务",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-cancel-billing",
        vendor=vendor,
    )
    with pytest.raises(BillingInvariantError, match="remain frozen"):
        finalize_oral_billing(conn, oral_task_id=cancelled.task_id)
    first_cancel = cancel_oral_task(conn, task_id=cancelled.task_id, actor=actor())
    replay_cancel = cancel_oral_task(conn, task_id=cancelled.task_id, actor=actor())
    assert first_cancel["status"] == replay_cancel["status"] == "CANCELLED"

    succeeded = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="成功任务",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-success-billing",
        vendor=vendor,
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES ('oral-final-result', NULL, 'oral_video', 'local://oral/final.mp4',
                  'final-hash', 9, 'video/mp4', 'employee_1')
        """
    )
    conn.execute(
        "UPDATE oral_tasks SET status = 'SUCCEEDED', result_asset_id = %s WHERE id = %s",
        ("oral-final-result", succeeded.task_id),
    )
    settled = finalize_oral_billing(conn, oral_task_id=succeeded.task_id)
    replayed = finalize_oral_billing(conn, oral_task_id=succeeded.task_id)
    conn.commit()

    assert settled.transaction_type == replayed.transaction_type == "SETTLE"
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert (wallet["available_credits"], wallet["reserved_credits"]) == (19, 0)
    rows = conn.execute(
        """
        SELECT oral_task_id, type FROM wallet_transactions
        WHERE oral_task_id IN (%s, %s)
        ORDER BY oral_task_id, type
        """,
        (cancelled.task_id, succeeded.task_id),
    ).fetchall()
    assert sorted(str(row["type"]) for row in rows) == [
        "RELEASE",
        "RESERVE",
        "RESERVE",
        "SETTLE",
    ]


@pytest.mark.parametrize("status", ["SUBMISSION_UNCERTAIN", "ARCHIVE_FAILED"])
def test_oral_billing_keeps_uncertain_and_archive_failed_reservations_frozen(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    status: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-billing-frozen-{status}.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    task = create_oral_task(
        conn,
        actor=actor(),
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="冻结任务",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key=f"oral-frozen-{status}",
    )
    conn.execute("UPDATE oral_tasks SET status = %s WHERE id = %s", (status, task.task_id))
    conn.commit()

    with pytest.raises(BillingInvariantError, match="remain frozen"):
        finalize_oral_billing(conn, oral_task_id=task.task_id)

    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert (wallet["available_credits"], wallet["reserved_credits"]) == (19, 1)


def test_create_oral_task_rejects_ready_but_unconfirmed_voice(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-unconfirmed-voice.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    conn.execute("UPDATE oral_voices SET confirmed = 0 WHERE id = %s", (voice_id,))
    vendor, transport = make_vendor()

    with pytest.raises(OralDomainError, match="确认"):
        create_oral_task(
            conn,
            actor=actor(),
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=voice_id,
            mode="TTS",
            title="未试听声音",
            script_text="文案",
            audio_asset_id=None,
            subtitle=None,
            idempotency_key="unconfirmed-voice",
            vendor=vendor,
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    ("audio_asset_id", "error_type"),
    [
        ("asset-src", OralDomainError),
        ("other-audio", HTTPException),
        ("pending-audio", OralDomainError),
    ],
)
def test_create_audio_oral_task_rejects_wrong_inaccessible_or_incomplete_asset(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    audio_asset_id: str,
    error_type: type[Exception],
) -> None:
    conn = seed_scene(tmp_path, f"oral-audio-invalid-{audio_asset_id}.db")
    avatar_id, _ = seed_ready_assets(conn)
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
        ("other-project", "employee_2", "Other Project"),
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (?, ?, 'oral_audio', ?, ?, ?, 'audio/mpeg', ?)
        """,
        (
            "other-audio",
            "other-project",
            "local://assets/other.mp3",
            "other-audio-hash",
            9,
            "employee_2",
        ),
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (?, ?, 'oral_audio', ?, '', 0, 'audio/mpeg', ?)
        """,
        ("pending-audio", "oral-project", "local://assets/pending.mp3", "employee_1"),
    )
    conn.commit()
    vendor, _ = make_vendor()

    with pytest.raises(error_type):
        create_oral_task(
            conn,
            actor=actor(),
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=None,
            mode="AUDIO",
            title="音频口播",
            script_text=None,
            audio_asset_id=audio_asset_id,
            subtitle=None,
            idempotency_key=f"invalid-{audio_asset_id}",
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
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'RUNNING', vendor_task_id = 'vt-task-2',
            submission_state = 'SUBMITTED'
        WHERE id = %s
        """,
        (created.task_id,),
    )
    conn.commit()

    # 任务已 RUNNING：供应商查询 DONE 并返回临时视频地址 → 归档为平台资产。
    transport.on(
        "GET",
        "/api/v2/hifly/video/task",
        envelope({"status": 3, "video_Url": "https://tmp.example/v.mp4", "duration": 32}),
    )
    transport.on("GET", "https://tmp.example/v.mp4", b"MP4BYTES")

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

    refreshed = refresh_oral_task(conn, task_id=created.task_id, actor=actor(), vendor=vendor)
    assert refreshed["status"] == "SUCCEEDED"
    assert refreshed["result_asset_id"]
    assert refreshed["duration_sec"] == 32

    asset = conn.execute(
        "SELECT kind, project_id FROM assets WHERE id = ?", (refreshed["result_asset_id"],)
    ).fetchone()
    assert asset["kind"] == "oral_video"
    assert asset["project_id"] is None


def test_task_create_never_calls_vendor_inside_request_transaction(
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
    assert transport.calls == []
    row = conn.execute(
        "SELECT status, submission_state, error_message FROM oral_tasks WHERE idempotency_key = ?",
        ("idem-key-0004",),
    ).fetchone()
    assert row["status"] == "QUEUED"
    assert row["submission_state"] == "LOCAL_PENDING"
    assert row["error_message"] is None


def test_oral_unit_price_defaults_and_reads_settings(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-price.db")
    assert oral_unit_price_fen(conn) == ORAL_UNIT_PRICE_FEN_DEFAULT == 1000
