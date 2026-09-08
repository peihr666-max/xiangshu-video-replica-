"""Oral digital-human domain tests (C1 slice ②).

Vendor transport is scripted; storage is stubbed at the module seam
(``app.oral.storage_for_asset`` / ``app.oral.get_media_storage``) so these
tests exercise clone flows, task lifecycle, idempotency, and pricing without
network or real buckets.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet

from app.auth import CurrentUser
from app.db import initialize_database
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyProtocolError
from app.media_tools import MediaToolFailed
from app.oral import (
    ORAL_UNIT_PRICE_FEN_DEFAULT,
    CloneOutcome,
    OralCloneLeaseLost,
    OralDomainError,
    OralOutcome,
    OralTaskLeaseLost,
    PreparedCloneWork,
    PreparedOralWork,
    acquire_oral_clone,
    acquire_oral_task,
    confirm_voice_clone,
    create_oral_task,
    fail_claimed_oral_task,
    finalize_oral_clone_work,
    finalize_oral_task_work,
    mark_oral_clone_provider_submission_started,
    mark_oral_provider_submission_started,
    oral_unit_price_fen,
    perform_oral_clone_work,
    perform_oral_task_work,
    prepare_oral_clone_work,
    prepare_oral_task_work,
    preserve_oral_clone_outcome_for_reconciliation,
    preserve_oral_task_outcome_for_reconciliation,
    reconcile_uncertain_oral_clone,
    record_oral_clone_consent,
    refresh_avatar_clone,
    refresh_voice_clone,
    renew_oral_clone_lease,
    renew_oral_task_lease,
    run_claimed_oral_clone,
    run_next_oral_task,
    start_avatar_clone,
    start_voice_clone,
)

_NOW = "2026-09-06 03:00:00"
_FAKE_MEDIA_SHA256 = "f12c3039fa8bf0aff5549f429f3decac524e9324a4ffb80faddd56d8a3de912e"


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


class _NeverStore:
    def put_object(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid provider media must not be archived")


class _RecordingStorage:
    def __init__(self) -> None:
        self.puts: list[tuple[str, bytes, str]] = []

    def put_object(self, key: str, content: bytes, *, content_type: str) -> None:
        self.puts.append((key, content, content_type))


def _raise_invalid_media(*_args: object, **_kwargs: object) -> None:
    raise MediaToolFailed("媒体文件无法验证，请稍后重试")


def test_clone_protocol_error_preserves_known_vendor_task_for_reconciliation() -> None:
    class InvalidStatusVendor:
        def avatar_task(self, _task_id: str) -> None:
            raise HiflyProtocolError("数字人服务返回了无效的任务状态")

    outcome = perform_oral_clone_work(
        PreparedCloneWork(
            lease={
                "id": "avatar-protocol-error",
                "status": "RUNNING",
                "clone_kind": "avatar",
                "vendor_task_id": "vendor-task",
            },
            vendor=InvalidStatusVendor(),  # type: ignore[arg-type]
            source_storage=None,
            source_key=None,
            source_extension=None,
            expected_source_sha256=None,
            result_storage=None,
        )
    )

    assert outcome.status == "SUBMISSION_UNCERTAIN"


def test_oral_protocol_error_preserves_known_vendor_task_and_reservation() -> None:
    class InvalidStatusVendor:
        def video_task(self, _task_id: str) -> None:
            raise HiflyProtocolError("数字人服务返回了无效的任务状态")

    outcome = perform_oral_task_work(
        PreparedOralWork(
            lease={"id": "oral-protocol-error", "status": "RUNNING", "vendor_task_id": "vt"},
            vendor=InvalidStatusVendor(),  # type: ignore[arg-type]
            audio_storage=None,
            audio_key=None,
            audio_extension=None,
            expected_source_sha256=None,
            result_storage=_NeverStore(),  # type: ignore[arg-type]
            avatar_vendor_id=None,
            voice_vendor_id=None,
            subtitle=None,
        )
    )

    assert outcome.status == "SUBMISSION_UNCERTAIN"


def test_clone_protocol_error_after_submission_requires_reconciliation() -> None:
    class SourceStorage:
        def get_object(self, _key: str) -> bytes:
            return b"valid-source"

    class InvalidCreateVendor:
        def create_upload_url(self, _extension: str) -> SimpleNamespace:
            return SimpleNamespace(file_id="source-file")

        def upload_file(self, _target: SimpleNamespace, _content: bytes) -> None:
            return None

        def create_avatar_by_video(self, **_kwargs: object) -> None:
            raise HiflyProtocolError("数字人服务未返回任务编号")

    outcome = perform_oral_clone_work(
        PreparedCloneWork(
            lease={
                "id": "avatar-submit-protocol-error",
                "status": "SUBMITTING",
                "clone_kind": "avatar",
                "source_kind": "VIDEO",
                "title": "提交后协议异常",
            },
            vendor=InvalidCreateVendor(),  # type: ignore[arg-type]
            source_storage=SourceStorage(),  # type: ignore[arg-type]
            source_key="source.mp4",
            source_extension="mp4",
            expected_source_sha256=None,
            result_storage=None,
        ),
        mark_submission_started=lambda: True,
    )

    assert outcome.status == "SUBMISSION_UNCERTAIN"


def test_oral_protocol_error_after_submission_requires_reconciliation() -> None:
    class InvalidCreateVendor:
        def create_video_by_tts(self, **_kwargs: object) -> None:
            raise HiflyProtocolError("数字人服务未返回任务编号")

    outcome = perform_oral_task_work(
        PreparedOralWork(
            lease={
                "id": "oral-submit-protocol-error",
                "status": "SUBMITTING",
                "mode": "TTS",
                "script_text": "测试文案",
                "title": "提交后协议异常",
            },
            vendor=InvalidCreateVendor(),  # type: ignore[arg-type]
            audio_storage=None,
            audio_key=None,
            audio_extension=None,
            expected_source_sha256=None,
            result_storage=None,
            avatar_vendor_id="avatar-1",
            voice_vendor_id="voice-1",
            subtitle=None,
        ),
        mark_submission_started=lambda: True,
    )

    assert outcome.status == "SUBMISSION_UNCERTAIN"


def test_invalid_voice_demo_is_rejected_before_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidDemoVendor:
        def voice_task(self, _task_id: str) -> SimpleNamespace:
            return SimpleNamespace(status="DONE", voice="voice-id", demo_url="https://tmp/demo")

        def download(self, _url: str) -> bytes:
            return b"<html>not audio</html>"

    monkeypatch.setattr("app.oral.require_media_stream", _raise_invalid_media, raising=False)
    outcome = perform_oral_clone_work(
        PreparedCloneWork(
            lease={
                "id": "voice-invalid-demo",
                "status": "RUNNING",
                "clone_kind": "voice",
                "vendor_task_id": "vendor-task",
            },
            vendor=InvalidDemoVendor(),  # type: ignore[arg-type]
            source_storage=None,
            source_key=None,
            source_extension=None,
            expected_source_sha256=None,
            result_storage=_NeverStore(),  # type: ignore[arg-type]
        )
    )

    assert outcome.status == "FAILED"


def test_invalid_oral_video_is_rejected_before_archive_and_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidVideoVendor:
        def video_task(self, _task_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                status="DONE",
                video_url="https://tmp/video",
                duration=30,
            )

        def download(self, _url: str) -> bytes:
            return b"<html>not video</html>"

    monkeypatch.setattr("app.oral.require_media_stream", _raise_invalid_media, raising=False)
    outcome = perform_oral_task_work(
        PreparedOralWork(
            lease={"id": "oral-invalid-video", "status": "RUNNING", "vendor_task_id": "vt"},
            vendor=InvalidVideoVendor(),  # type: ignore[arg-type]
            audio_storage=None,
            audio_key=None,
            audio_extension=None,
            expected_source_sha256=None,
            result_storage=_NeverStore(),  # type: ignore[arg-type]
            avatar_vendor_id=None,
            voice_vendor_id=None,
            subtitle=None,
        )
    )

    assert outcome.status == "FAILED"


def test_voice_demo_lost_lease_after_validation_is_not_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReadyVoiceVendor:
        def voice_task(self, _task_id: str) -> SimpleNamespace:
            return SimpleNamespace(status="DONE", voice="voice-id", demo_url="https://tmp/demo")

        def download(self, _url: str) -> bytes:
            return b"VALID-MP3"

    storage = _RecordingStorage()
    monkeypatch.setattr("app.oral.require_media_stream", lambda *_args, **_kwargs: None)
    renewals = iter((True, True, True, False))

    with pytest.raises(OralCloneLeaseLost, match="租约已失效"):
        perform_oral_clone_work(
            PreparedCloneWork(
                lease={
                    "id": "voice-validation-fence",
                    "status": "RUNNING",
                    "clone_kind": "voice",
                    "vendor_task_id": "vendor-task",
                },
                vendor=ReadyVoiceVendor(),  # type: ignore[arg-type]
                source_storage=None,
                source_key=None,
                source_extension=None,
                expected_source_sha256=None,
                result_storage=storage,  # type: ignore[arg-type]
            ),
            renew_lease=lambda: next(renewals),
        )

    assert storage.puts == []


def test_oral_video_lost_lease_after_validation_is_not_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReadyVideoVendor:
        def video_task(self, _task_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                status="DONE",
                video_url="https://tmp/video",
                duration=30,
            )

        def download(self, _url: str) -> bytes:
            return b"VALID-MP4"

    storage = _RecordingStorage()
    monkeypatch.setattr("app.oral.require_media_stream", lambda *_args, **_kwargs: None)
    renewals = iter((True, True, True, False))

    with pytest.raises(OralTaskLeaseLost, match="租约已失效"):
        perform_oral_task_work(
            PreparedOralWork(
                lease={
                    "id": "oral-validation-fence",
                    "status": "RUNNING",
                    "vendor_task_id": "vendor-task",
                },
                vendor=ReadyVideoVendor(),  # type: ignore[arg-type]
                audio_storage=None,
                audio_key=None,
                audio_extension=None,
                expected_source_sha256=None,
                result_storage=storage,  # type: ignore[arg-type]
                avatar_vendor_id=None,
                voice_vendor_id=None,
                subtitle=None,
            ),
            renew_lease=lambda: next(renewals),
        )

    assert storage.puts == []


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
            'f12c3039fa8bf0aff5549f429f3decac524e9324a4ffb80faddd56d8a3de912e',
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
            'f12c3039fa8bf0aff5549f429f3decac524e9324a4ffb80faddd56d8a3de912e',
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
                            "source_sha256": _FAKE_MEDIA_SHA256,
                            "purpose": "oral_avatar_clone",
                        },
                        {
                            "identity_id": "ident-1",
                            "source_asset_id": "asset-audio",
                            "source_sha256": _FAKE_MEDIA_SHA256,
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
            status, source_kind, source_asset_id, consent_id
        )
        VALUES (
            'avatar-ready', 'ident-1', 'employee_1', '张工分身',
            'vendor-avatar-9', 'READY', 'VIDEO', 'asset-src', 'asset-auth'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO oral_voices (
            id, identity_id, owner_user_id, title, vendor_voice_id,
            status, source_asset_id, consent_id, demo_asset_id, confirmed
        )
        VALUES (
            'voice-ready', 'ident-1', 'employee_1', '张工声音',
            'vendor-voice-9', 'READY', 'asset-audio', 'asset-auth', 'demo-ready', 1
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


def test_quicktime_avatar_preserves_mov_upload_extension(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
) -> None:
    conn = seed_scene(tmp_path, "oral-avatar-mov.db")
    conn.execute("UPDATE assets SET content_type = 'video/quicktime' WHERE id = 'asset-src'")
    fake_source_storage.payload = b"\x00\x00\x00\x14ftypqt  quicktime"
    conn.execute(
        "UPDATE assets SET sha256 = %s WHERE id = 'asset-src'",
        (hashlib.sha256(fake_source_storage.payload).hexdigest(),),
    )
    record_oral_clone_consent(
        conn,
        actor=actor(),
        identity_id="ident-1",
        source_asset_id="asset-src",
        purpose="oral_avatar_clone",
    )
    conn.commit()
    vendor, transport = make_vendor()

    def upload_target(body: bytes | None) -> bytes:
        assert json.loads(body or b"{}")["file_extension"] == "mov"
        return envelope(
            {
                "upload_url": "https://up.example/mov",
                "content_type": "video/quicktime",
                "file_id": "mov-file",
            }
        )

    transport.on("POST", "/api/v2/hifly/tool/create_upload_url", upload_target)
    transport.on("POST", "/api/v2/hifly/avatar/create_by_video", envelope({"task_id": "mov-task"}))
    created = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="MOV 分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="avatar-mov",
    )
    lease = acquire_oral_clone(conn, worker_id="mov-worker")
    assert lease is not None

    run_claimed_oral_clone(conn, lease=lease, worker_id="mov-worker", vendor=vendor)

    row = conn.execute(
        "SELECT status, vendor_task_id FROM oral_avatars WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert tuple(row) == ("RUNNING", "mov-task")


@pytest.mark.parametrize(
    ("content_type", "extension"),
    [("video/mp4", "mp4"), ("video/quicktime", "mov"), ("video/webm", "webm")],
)
def test_avatar_video_extension_accepts_only_documented_content_types(
    content_type: str,
    extension: str,
) -> None:
    from app.oral import _extension_for

    assert _extension_for({"content_type": content_type}, "VIDEO") == extension
    with pytest.raises(OralDomainError, match="视频格式不支持"):
        _extension_for({"content_type": "video/x-msvideo"}, "VIDEO")


def test_sqlite_worker_finalizes_clone_prepare_failure_and_processes_next_clone(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.generation_worker import run_worker_once

    conn = seed_scene(tmp_path, "oral-clone-prepare-starvation.db")
    conn.execute(
        "INSERT INTO oral_avatars (id, identity_id, owner_user_id, title, status, "
        "source_kind, source_asset_id, consent_id, idempotency_key, request_hash, "
        "created_at) VALUES "
        "('a-broken-clone', 'ident-1', 'employee_1', '坏素材', 'PENDING', 'VIDEO', "
        "'missing-source', 'asset-auth', 'broken-clone', 'broken-hash', "
        "'2000-01-01T00:00:00+00:00')"
    )
    healthy = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="后续分身",
        source_asset_id="asset-src",
        source_kind="VIDEO",
        consent_id="asset-auth",
        idempotency_key="healthy-clone",
    )
    conn.commit()
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/healthy",
                "content_type": "video/mp4",
                "file_id": "healthy-file",
            }
        ),
    )
    transport.on(
        "POST", "/api/v2/hifly/avatar/create_by_video", envelope({"task_id": "healthy-task"})
    )
    monkeypatch.setattr("app.oral.hifly_client_from_settings", lambda _conn: vendor)

    processed = run_worker_once(
        conn,
        worker_id="clone-starvation-worker",
        storage=fake_source_storage,  # type: ignore[arg-type]
        max_tasks=2,
    )

    assert processed == 2
    rows = conn.execute(
        "SELECT id, status, vendor_task_id FROM oral_avatars WHERE id IN ('a-broken-clone', %s)",
        (healthy.task_id,),
    ).fetchall()
    states = {str(row["id"]): (str(row["status"]), row["vendor_task_id"]) for row in rows}
    assert states == {
        "a-broken-clone": ("FAILED", None),
        healthy.task_id: ("RUNNING", "healthy-task"),
    }


def test_sqlite_clone_prepare_failure_logs_context_and_persists_safe_message(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.generation_worker import run_worker_once

    conn = seed_scene(tmp_path, "oral-clone-safe-error.db")
    conn.execute(
        "INSERT INTO oral_avatars (id, identity_id, owner_user_id, title, status, "
        "source_kind, source_asset_id, consent_id, idempotency_key, request_hash) VALUES "
        "('safe-error-clone', 'ident-1', 'employee_1', '配置失败', 'PENDING', 'VIDEO', "
        "'asset-src', 'asset-auth', 'safe-error-key', 'safe-error-hash')"
    )
    conn.commit()
    secret_detail = "private-config-path-and-token"

    def raise_prepare_error(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError(secret_detail)

    monkeypatch.setattr("app.generation_worker.run_claimed_oral_clone", raise_prepare_error)
    worker_logger = logging.getLogger("app.generation_worker")
    monkeypatch.setattr(worker_logger, "handlers", [*worker_logger.handlers, caplog.handler])
    caplog.set_level(logging.WARNING, logger="app.generation_worker")

    assert (
        run_worker_once(
            conn,
            worker_id="safe-error-worker",
            storage=fake_source_storage,  # type: ignore[arg-type]
            max_tasks=1,
        )
        == 1
    )

    row = conn.execute(
        "SELECT status, error_message FROM oral_avatars WHERE id = 'safe-error-clone'"
    ).fetchone()
    assert tuple(row) == ("FAILED", "克隆服务配置或依赖暂不可用，请稍后重试")
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "task_id=safe-error-clone" in message
        and "clone_kind=avatar" in message
        and "error_type=RuntimeError" in message
        for message in messages
    )
    assert not any("lease token was replaced" in message for message in messages)
    assert secret_detail not in caplog.text
    assert secret_detail not in str(row["error_message"])


def test_sqlite_clone_prepare_failure_logs_replaced_token_without_overwrite(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.generation_worker import run_worker_once

    conn = seed_scene(tmp_path, "oral-clone-stale-error.db")
    conn.execute(
        "INSERT INTO oral_avatars (id, identity_id, owner_user_id, title, status, "
        "source_kind, source_asset_id, consent_id, idempotency_key, request_hash) VALUES "
        "('stale-error-clone', 'ident-1', 'employee_1', '旧租约', 'PENDING', 'VIDEO', "
        "'asset-src', 'asset-auth', 'stale-error-key', 'stale-error-hash')"
    )
    conn.commit()

    secret_detail = "stale-worker-private-path-and-token"

    def replace_token_then_fail(
        active_conn: BusinessConnection,
        *,
        lease: dict[str, Any],
        worker_id: str,
    ) -> str:
        assert worker_id == "stale-error-worker"
        active_conn.execute(
            "UPDATE oral_avatars SET lease_token = 'replacement-token' WHERE id = %s",
            (str(lease["id"]),),
        )
        active_conn.commit()
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(
        "app.generation_worker.run_claimed_oral_clone",
        replace_token_then_fail,
    )
    worker_logger = logging.getLogger("app.generation_worker")
    monkeypatch.setattr(worker_logger, "handlers", [*worker_logger.handlers, caplog.handler])
    caplog.set_level(logging.WARNING, logger="app.generation_worker")

    assert (
        run_worker_once(
            conn,
            worker_id="stale-error-worker",
            storage=fake_source_storage,  # type: ignore[arg-type]
            max_tasks=1,
        )
        == 1
    )

    row = conn.execute(
        "SELECT status, lease_token, error_message FROM oral_avatars WHERE id = 'stale-error-clone'"
    ).fetchone()
    assert tuple(row) == ("SUBMITTING", "replacement-token", None)
    messages = [record.getMessage() for record in caplog.records]
    assert any("task_id=stale-error-clone" in message for message in messages)
    assert any("lease token was replaced" in message for message in messages)
    assert secret_detail not in caplog.text


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
    validated: list[tuple[bytes, str, str]] = []
    monkeypatch.setattr(
        "app.oral.require_media_stream",
        lambda content, *, extension, expected_stream: validated.append(
            (content, extension, expected_stream)
        ),
    )

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
    assert validated == [(b"DEMO", "mp3", "audio")]


@pytest.mark.parametrize(
    ("content_type", "expected_extension"),
    [
        ("audio/mpeg", "mp3"),
        ("audio/mp3", "mp3"),
        ("audio/wav", "wav"),
        ("audio/x-wav", "wav"),
        ("audio/mp4", "m4a"),
        ("audio/m4a", "m4a"),
        ("audio/x-m4a", "m4a"),
    ],
)
def test_voice_clone_preserves_validated_audio_extension(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    content_type: str,
    expected_extension: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-voice-{expected_extension}.db")
    conn.execute("UPDATE assets SET content_type = %s WHERE id = 'asset-audio'", (content_type,))
    created = start_voice_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="声音扩展名",
        source_asset_id="asset-audio",
        consent_id="asset-auth",
        idempotency_key=f"voice-extension-{expected_extension}-{content_type}",
    )
    lease = acquire_oral_clone(conn, worker_id="voice-extension-worker")
    assert lease is not None
    vendor, transport = make_vendor()

    work = prepare_oral_clone_work(conn, lease=lease, vendor=vendor)

    assert work.lease["id"] == created.task_id
    assert work.source_extension == expected_extension
    assert transport.calls == []


@pytest.mark.parametrize("content_type", ["audio/webm", "audio/ogg", "audio/flac"])
def test_voice_clone_rejects_unsupported_audio_mime_before_provider_call(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    content_type: str,
) -> None:
    suffix = content_type.rsplit("/", 1)[-1]
    conn = seed_scene(tmp_path, f"oral-voice-unsupported-{suffix}.db")
    conn.execute("UPDATE assets SET content_type = %s WHERE id = 'asset-audio'", (content_type,))
    start_voice_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="未知声音格式",
        source_asset_id="asset-audio",
        consent_id="asset-auth",
        idempotency_key="voice-extension-unknown",
    )
    lease = acquire_oral_clone(conn, worker_id="voice-extension-worker")
    assert lease is not None
    vendor, transport = make_vendor()

    with pytest.raises(OralDomainError, match="声音素材格式不支持"):
        prepare_oral_clone_work(conn, lease=lease, vendor=vendor)

    assert transport.calls == []


@pytest.mark.parametrize(
    ("payload", "expected_extension"),
    [
        (b"\xff\xd8\xff\xe0jpeg-avatar", "jpg"),
        (b"\x89PNG\r\n\x1a\npng-avatar", "png"),
        (b"RIFF\x10\x00\x00\x00WEBPwebp-avatar", "webp"),
    ],
)
def test_image_avatar_uses_verified_mime_extension(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    payload: bytes,
    expected_extension: str,
) -> None:
    from app.oral import acquire_oral_clone, run_claimed_oral_clone

    conn = seed_scene(tmp_path, "oral-image-worker.db")
    conn.execute("UPDATE assets SET content_type = 'image/jpeg' WHERE id = 'asset-src'")
    fake_source_storage.payload = payload
    conn.execute(
        "UPDATE assets SET sha256 = %s WHERE id = 'asset-src'",
        (hashlib.sha256(payload).hexdigest(),),
    )
    record_oral_clone_consent(
        conn,
        actor=actor(),
        identity_id="ident-1",
        source_asset_id="asset-src",
        purpose="oral_avatar_clone",
    )
    conn.commit()
    vendor, transport = make_vendor()

    def upload_target(body: bytes | None) -> bytes:
        assert json.loads(body or b"{}")["file_extension"] == expected_extension
        return envelope(
            {
                "upload_url": "https://up.example/i",
                "content_type": "image/jpeg",
                "file_id": "image-file",
            }
        )

    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        upload_target,
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


def test_image_avatar_rejects_invalid_magic_before_any_provider_call(
    tmp_path: Path, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-invalid-image-worker.db")
    conn.execute("UPDATE assets SET content_type = 'image/jpeg' WHERE id = 'asset-src'")
    fake_source_storage.payload = b"not-an-image"
    conn.execute(
        "UPDATE assets SET sha256 = %s WHERE id = 'asset-src'",
        (hashlib.sha256(fake_source_storage.payload).hexdigest(),),
    )
    record_oral_clone_consent(
        conn,
        actor=actor(),
        identity_id="ident-1",
        source_asset_id="asset-src",
        purpose="oral_avatar_clone",
    )
    conn.commit()
    vendor, transport = make_vendor()
    started = start_avatar_clone(
        conn,
        actor=actor(),
        identity_id="ident-1",
        title="损坏图片分身",
        source_asset_id="asset-src",
        source_kind="IMAGE",
        consent_id="asset-auth",
        idempotency_key="avatar-invalid-image",
    )
    lease = acquire_oral_clone(conn, worker_id="clone-worker")
    assert lease is not None

    run_claimed_oral_clone(conn, lease=lease, worker_id="clone-worker", vendor=vendor)

    row = conn.execute(
        "SELECT status, vendor_task_id FROM oral_avatars WHERE id = %s",
        (started.task_id,),
    ).fetchone()
    assert tuple(row) == ("FAILED", None)
    assert transport.calls == []


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_clone_pre_submit_storage_failure_is_terminal_not_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_source_storage: FakeSourceStorage,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-prepare-failure.db")
    vendor, transport = make_vendor()

    def fail_read(_key: str) -> bytes:
        assert not conn.raw.in_transaction
        raise OSError("storage unavailable")

    monkeypatch.setattr(fake_source_storage, "get_object", fail_read)
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="分身准备失败",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-prepare-failure",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="声音准备失败",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-prepare-failure",
        )
        table = "oral_voices"
    lease = acquire_oral_clone(conn, worker_id="clone-prepare-worker")
    assert lease is not None
    run_claimed_oral_clone(conn, lease=lease, worker_id="clone-prepare-worker", vendor=vendor)

    row = conn.execute(
        f"SELECT status, provider_started_at FROM {table} WHERE id = %s",  # noqa: S608
        (created.task_id,),
    ).fetchone()
    assert tuple(row) == ("FAILED", None)
    assert not any(
        "/avatar/create_" in url or url.endswith("/voice/create") for _, url in transport.calls
    )


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_sqlite_clone_lease_fences_same_day_expiry_and_replaced_token(
    tmp_path: Path,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-lease-fence.db")
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="分身租约",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-lease-fence",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="声音租约",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-lease-fence",
        )
        table = "oral_voices"
    lease = acquire_oral_clone(conn, worker_id="clone-old-worker")
    assert lease is not None
    assert renew_oral_clone_lease(conn, lease=lease)
    assert not conn.raw.in_transaction

    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    conn.execute(
        f"UPDATE {table} SET locked_until = %s WHERE id = %s",  # noqa: S608
        (expired, created.task_id),
    )
    conn.commit()
    assert not renew_oral_clone_lease(conn, lease=lease)
    assert not mark_oral_clone_provider_submission_started(conn, lease=lease)
    assert not conn.raw.in_transaction

    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    conn.execute(
        f"UPDATE {table} SET locked_until = %s WHERE id = %s",  # noqa: S608
        (future, created.task_id),
    )
    conn.commit()
    assert mark_oral_clone_provider_submission_started(conn, lease=lease)
    assert not conn.raw.in_transaction
    conn.execute(
        f"UPDATE {table} SET lease_token = 'replacement-token' WHERE id = %s",  # noqa: S608
        (created.task_id,),
    )
    conn.commit()
    assert not renew_oral_clone_lease(conn, lease=lease)
    assert not mark_oral_clone_provider_submission_started(conn, lease=lease)


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_clone_stops_between_external_steps_when_lease_is_replaced(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-step-fence.db")
    vendor, transport = make_vendor()
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/clone",
                "content_type": "application/octet-stream",
                "file_id": "clone-file",
            }
        ),
    )
    if clone_kind == "avatar":
        start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="失效分身",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-step-fence",
        )
    else:
        start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="失效声音",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-step-fence",
        )
    lease = acquire_oral_clone(conn, worker_id="clone-step-worker")
    assert lease is not None
    work = prepare_oral_clone_work(conn, lease=lease, vendor=vendor)
    conn.commit()
    renewals = iter((True, True, False))

    with pytest.raises(OralCloneLeaseLost, match="租约已失效"):
        perform_oral_clone_work(
            work,
            renew_lease=lambda: next(renewals),
            mark_submission_started=lambda: pytest.fail("provider boundary must not be reached"),
        )

    assert any(url.endswith("/tool/create_upload_url") for _, url in transport.calls)
    assert not any(method == "PUT" for method, _ in transport.calls)
    assert not any(
        "/avatar/create_" in url or url.endswith("/voice/create") for _, url in transport.calls
    )


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_sqlite_clone_provider_boundary_survives_crash_without_paid_replay(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-provider-crash.db")
    vendor, transport = make_vendor()
    endpoint = (
        "/api/v2/hifly/avatar/create_by_video"
        if clone_kind == "avatar"
        else "/api/v2/hifly/voice/create"
    )
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/clone",
                "content_type": "application/octet-stream",
                "file_id": "clone-file",
            }
        ),
    )

    def crash_during_create(_body: bytes | None) -> bytes:
        assert not conn.raw.in_transaction
        raise KeyboardInterrupt("clone worker crashed")

    transport.on("POST", endpoint, crash_during_create)
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="崩溃分身",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-provider-crash",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="崩溃声音",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-provider-crash",
        )
        table = "oral_voices"
    lease = acquire_oral_clone(conn, worker_id="clone-crash-worker")
    assert lease is not None
    with pytest.raises(KeyboardInterrupt, match="clone worker crashed"):
        run_claimed_oral_clone(conn, lease=lease, worker_id="clone-crash-worker", vendor=vendor)
    assert not conn.raw.in_transaction
    row = conn.execute(
        f"SELECT status, provider_started_at FROM {table} WHERE id = %s",  # noqa: S608
        (created.task_id,),
    ).fetchone()
    assert row["status"] == "SUBMITTING"
    assert row["provider_started_at"] is not None

    conn.execute(
        f"UPDATE {table} SET locked_until = %s WHERE id = %s",  # noqa: S608
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), created.task_id),
    )
    conn.commit()
    assert acquire_oral_clone(conn, worker_id="clone-replacement-worker") is None
    recovered = conn.execute(
        f"SELECT status, lease_token FROM {table} WHERE id = %s",  # noqa: S608
        (created.task_id,),
    ).fetchone()
    assert tuple(recovered) == ("SUBMISSION_UNCERTAIN", None)
    assert (
        sum(1 for method, url in transport.calls if method == "POST" and url.endswith(endpoint))
        == 1
    )


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_uncertain_clone_can_be_discarded_for_safe_manual_recovery(
    tmp_path: Path,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-reconcile.db")
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="待人工处理分身",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-manual-reconcile",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="待人工处理声音",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-manual-reconcile",
        )
        table = "oral_voices"
    conn.execute(
        f"UPDATE {table} SET status = 'SUBMISSION_UNCERTAIN' WHERE id = %s",  # noqa: S608
        (created.task_id,),
    )
    conn.commit()

    resolved = reconcile_uncertain_oral_clone(
        conn,
        clone_kind=clone_kind,
        clone_id=created.task_id,
        outcome="DISCARD",
    )
    conn.commit()

    assert resolved["status"] == "FAILED"
    with pytest.raises(OralDomainError, match="仅提交结果不确定"):
        reconcile_uncertain_oral_clone(
            conn,
            clone_kind=clone_kind,
            clone_id=created.task_id,
            outcome="DISCARD",
        )


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_pre_submit_failed_outcome_stays_terminal_when_finalize_must_be_retried(
    tmp_path: Path,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-failed-preserve.db")
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="分身失败",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-failed-preserve",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="声音失败",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-failed-preserve",
        )
        table = "oral_voices"
    lease = acquire_oral_clone(conn, worker_id="clone-failed-worker")
    assert lease is not None

    assert preserve_oral_clone_outcome_for_reconciliation(
        conn,
        lease=lease,
        outcome=CloneOutcome(status="FAILED", error_message="提交前素材读取失败"),
        cause=RuntimeError("first finalize failed"),
    )
    conn.commit()

    row = conn.execute(
        f"SELECT status, provider_started_at FROM {table} WHERE id = %s",  # noqa: S608
        (created.task_id,),
    ).fetchone()
    assert tuple(row) == ("FAILED", None)


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
        project_id="project-1",
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
        project_id="project-1",
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
            project_id="project-1",
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
        project_id="project-1",
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
        project_id="project-2",
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
            project_id="project-1",
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


def test_tts_oral_task_requires_explicit_owned_project(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-project-required.db")
    avatar_id, voice_id = seed_ready_assets(conn)

    with pytest.raises(OralDomainError, match="请选择口播所属项目"):
        create_oral_task(
            conn,
            actor=actor(),
            project_id=None,
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=voice_id,
            mode="TTS",
            title="明确项目",
            script_text="文案",
            audio_asset_id=None,
            subtitle=None,
            idempotency_key="project-required",
        )


def test_tts_oral_task_rejects_subtitle_collision_before_reserving(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-subtitle-collision.db")
    avatar_id, voice_id = seed_ready_assets(conn)

    with pytest.raises(OralDomainError, match="字幕参数不受支持"):
        create_oral_task(
            conn,
            actor=actor(),
            project_id="project-1",
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=voice_id,
            mode="TTS",
            title="字幕碰撞",
            script_text="文案",
            audio_asset_id=None,
            subtitle={"avatar": "other-avatar"},
            idempotency_key="subtitle-collision",
        )

    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(wallet) == (10, 0)


def test_audio_oral_task_derives_project_and_rejects_mismatch(tmp_path: Path) -> None:
    conn = seed_scene(tmp_path, "oral-audio-project.db")
    avatar_id, _ = seed_ready_assets(conn)

    created = create_oral_task(
        conn,
        actor=actor(),
        project_id=None,
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="音频口播",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key="audio-project-derived",
    )
    row = conn.execute(
        "SELECT project_id FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert row["project_id"] == "project-1"

    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES ('project-other', 'employee_1', 'O')"
    )
    with pytest.raises(OralDomainError, match="所属项目不一致"):
        create_oral_task(
            conn,
            actor=actor(),
            project_id="project-other",
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=None,
            mode="AUDIO",
            title="错误项目",
            script_text=None,
            audio_asset_id="asset-audio",
            subtitle=None,
            idempotency_key="audio-project-mismatch",
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
        project_id="project-1",
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
    validated: list[tuple[bytes, str, str]] = []
    monkeypatch.setattr(
        "app.oral.require_media_stream",
        lambda content, *, extension, expected_stream: validated.append(
            (content, extension, expected_stream)
        ),
    )
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
    assert validated == [
        (b"MP4BYTES", "mp4", "video"),
        (b"MP4BYTES", "mp4", "audio"),
    ]
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
        project_id="project-1",
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


def test_audio_pre_submit_storage_failure_releases_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_source_storage: FakeSourceStorage
) -> None:
    conn = seed_scene(tmp_path, "oral-audio-local-failure.db")
    avatar_id, _ = seed_ready_assets(conn)
    vendor, transport = make_vendor()

    def fail_read(_key: str) -> bytes:
        raise OSError("storage unavailable")

    monkeypatch.setattr(fake_source_storage, "get_object", fail_read)
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id=None,
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="本地准备失败",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key="audio-local-failure",
    )

    run_next_oral_task(conn, worker_id="worker-local-failure", vendor=vendor)

    task = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(task) == ("FAILED", None)
    assert tuple(wallet) == (10, 0)
    assert not any(url.endswith("/video/create_by_audio") for _, url in transport.calls)


@pytest.mark.parametrize(
    ("content_type", "expected_extension"),
    [("audio/mpeg", "mp3"), ("audio/mp4", "m4a"), ("audio/wav", "wav")],
)
def test_audio_oral_upload_uses_validated_source_extension(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    content_type: str,
    expected_extension: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-audio-upload-{expected_extension}.db")
    avatar_id, _ = seed_ready_assets(conn)
    conn.execute("UPDATE assets SET content_type = %s WHERE id = 'asset-audio'", (content_type,))
    conn.commit()
    vendor, transport = make_vendor()

    def upload_target(body: bytes | None) -> bytes:
        assert json.loads(body or b"{}")["file_extension"] == expected_extension
        return envelope(
            {
                "upload_url": "https://up.example/audio",
                "content_type": content_type,
                "file_id": "audio-file",
            }
        )

    transport.on("POST", "/api/v2/hifly/tool/create_upload_url", upload_target)
    transport.on("POST", "/api/v2/hifly/video/create_by_audio", envelope({"task_id": "audio-task"}))
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id=None,
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="音频口播",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key=f"audio-upload-{expected_extension}",
    )

    assert run_next_oral_task(conn, worker_id="audio-worker", vendor=vendor) == created.task_id
    task = conn.execute(
        "SELECT status, vendor_task_id FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert tuple(task) == ("RUNNING", "audio-task")


@pytest.mark.parametrize("content_type", ["audio/webm", "video/mp4", "image/jpeg"])
def test_audio_oral_creation_rejects_unsupported_mime_before_reservation(
    tmp_path: Path,
    content_type: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-audio-invalid-{content_type.replace('/', '-')}.db")
    avatar_id, _ = seed_ready_assets(conn)
    conn.execute("UPDATE assets SET content_type = %s WHERE id = 'asset-audio'", (content_type,))
    vendor, transport = make_vendor()

    with pytest.raises(OralDomainError, match="声音素材格式不支持"):
        create_oral_task(
            conn,
            actor=actor(),
            project_id=None,
            identity_id="ident-1",
            avatar_id=avatar_id,
            voice_id=None,
            mode="AUDIO",
            title="非法音频",
            script_text=None,
            audio_asset_id="asset-audio",
            subtitle=None,
            idempotency_key=f"audio-invalid-{content_type}",
            vendor=vendor,
        )

    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(wallet) == (10, 0)
    assert conn.execute("SELECT COUNT(*) FROM oral_tasks").fetchone()[0] == 0
    assert transport.calls == []


def test_audio_oral_prepare_rejects_changed_mime_and_releases_reservation(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
) -> None:
    conn = seed_scene(tmp_path, "oral-audio-mime-changed.db")
    avatar_id, _ = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id=None,
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="素材变化",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key="audio-mime-changed",
    )
    conn.execute("UPDATE assets SET content_type = 'audio/webm' WHERE id = 'asset-audio'")
    conn.commit()

    assert run_next_oral_task(conn, worker_id="audio-worker", vendor=vendor) == created.task_id

    task = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    ledger = conn.execute(
        "SELECT type FROM wallet_transactions WHERE oral_task_id = %s ORDER BY created_at, type",
        (created.task_id,),
    ).fetchall()
    assert tuple(task) == ("FAILED", None)
    assert tuple(wallet) == (10, 0)
    assert [row["type"] for row in ledger] == ["RELEASE", "RESERVE"]
    assert transport.calls == []


def test_oral_submission_revalidates_authorization_before_provider(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
) -> None:
    conn = seed_scene(tmp_path, "oral-authorization-recheck.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="授权过期",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-authorization-recheck",
    )
    conn.execute(
        "UPDATE person_identities SET authorization_status = 'EXPIRED' WHERE id = 'ident-1'"
    )
    conn.commit()

    assert (
        run_next_oral_task(conn, worker_id="authorization-worker", vendor=vendor) == created.task_id
    )

    task = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(task) == ("FAILED", None)
    assert tuple(wallet) == (10, 0)
    assert transport.calls == []


def test_oral_submission_revalidates_at_paid_provider_boundary(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
) -> None:
    conn = seed_scene(tmp_path, "oral-paid-boundary-recheck.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="出网前授权变化",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-paid-boundary-recheck",
    )
    lease = acquire_oral_task(conn, worker_id="boundary-worker")
    assert lease is not None
    work = prepare_oral_task_work(conn, lease=lease, vendor=vendor)
    conn.commit()
    conn.execute(
        "UPDATE person_identities SET authorization_status = 'EXPIRED' WHERE id = 'ident-1'"
    )
    conn.commit()

    outcome = perform_oral_task_work(
        work,
        mark_submission_started=lambda: mark_oral_provider_submission_started(conn, lease=lease),
    )
    assert outcome.status == "FAILED"
    assert finalize_oral_task_work(conn, work=work, outcome=outcome)
    conn.commit()

    task = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(task) == ("FAILED", None)
    assert tuple(wallet) == (10, 0)
    assert transport.calls == []


@pytest.mark.parametrize(
    "invalidate_sql",
    [
        "UPDATE oral_avatars SET status = 'FAILED' WHERE id = 'avatar-ready'",
        "UPDATE oral_voices SET confirmed = 0 WHERE id = 'voice-ready'",
        "UPDATE assets SET metadata_json = '{}' WHERE id = 'asset-auth'",
    ],
)
def test_oral_submission_revalidates_clone_state_and_consent_before_provider(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    invalidate_sql: str,
) -> None:
    conn = seed_scene(tmp_path, "oral-resource-recheck.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="资源重验",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-resource-recheck",
    )
    conn.execute(invalidate_sql)
    conn.commit()

    assert run_next_oral_task(conn, worker_id="resource-worker", vendor=vendor) == created.task_id

    task = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(task) == ("FAILED", None)
    assert tuple(wallet) == (10, 0)
    assert transport.calls == []


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_clone_rejects_downloaded_source_hash_mismatch_before_provider(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-source-hash.db")
    vendor, transport = make_vendor()
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="源素材变化",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-source-hash",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="源素材变化",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-source-hash",
        )
        table = "oral_voices"
    fake_source_storage.payload = b"changed-source-bytes"
    lease = acquire_oral_clone(conn, worker_id="source-hash-worker")
    assert lease is not None

    assert (
        run_claimed_oral_clone(conn, lease=lease, worker_id="source-hash-worker", vendor=vendor)
        == created.task_id
    )

    row = conn.execute(
        f"SELECT status, provider_started_at FROM {table} WHERE id = %s",  # noqa: S608
        (created.task_id,),
    ).fetchone()
    assert tuple(row) == ("FAILED", None)
    assert transport.calls == []


@pytest.mark.parametrize("clone_kind", ["avatar", "voice"])
def test_clone_revalidates_current_authorization_before_provider(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    clone_kind: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-{clone_kind}-authorization-recheck.db")
    vendor, transport = make_vendor()
    if clone_kind == "avatar":
        created = start_avatar_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="授权变化",
            source_asset_id="asset-src",
            source_kind="VIDEO",
            consent_id="asset-auth",
            idempotency_key="avatar-authorization-recheck",
        )
        table = "oral_avatars"
    else:
        created = start_voice_clone(
            conn,
            actor=actor(),
            identity_id="ident-1",
            title="授权变化",
            source_asset_id="asset-audio",
            consent_id="asset-auth",
            idempotency_key="voice-authorization-recheck",
        )
        table = "oral_voices"
    conn.execute("UPDATE assets SET metadata_json = '{}' WHERE id = 'asset-auth'")
    conn.commit()
    lease = acquire_oral_clone(conn, worker_id="authorization-worker")
    assert lease is not None

    assert (
        run_claimed_oral_clone(conn, lease=lease, worker_id="authorization-worker", vendor=vendor)
        == created.task_id
    )

    row = conn.execute(
        f"SELECT status, provider_started_at FROM {table} WHERE id = %s",  # noqa: S608
        (created.task_id,),
    ).fetchone()
    assert tuple(row) == ("FAILED", None)
    assert transport.calls == []


def test_audio_oral_rejects_downloaded_source_hash_mismatch_and_releases_reservation(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
) -> None:
    conn = seed_scene(tmp_path, "oral-audio-source-hash.db")
    avatar_id, _ = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id=None,
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="音频变化",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key="audio-source-hash",
    )
    fake_source_storage.payload = b"changed-audio-bytes"

    assert (
        run_next_oral_task(conn, worker_id="source-hash-worker", vendor=vendor) == created.task_id
    )

    task = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(task) == ("FAILED", None)
    assert tuple(wallet) == (10, 0)
    assert transport.calls == []


def test_sqlite_running_oral_prepare_failure_is_preserved_without_starving_queue(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = seed_scene(tmp_path, "oral-running-prepare-failure.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    transport.on("POST", "/api/v2/hifly/video/create_by_tts", envelope({"task_id": "vendor-1"}))
    first = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="首任务",
        script_text="文案一",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="running-prepare-first",
    )
    assert run_next_oral_task(conn, worker_id="worker", vendor=vendor) == first.task_id
    conn.execute(
        "UPDATE oral_tasks SET locked_until = '2020-01-01T00:00:00+00:00', "
        "next_poll_at = '2020-01-01T00:00:00+00:00', "
        "created_at = '2000-01-01T00:00:00+00:00' WHERE id = %s",
        (first.task_id,),
    )
    second = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="后续任务",
        script_text="文案二",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="running-prepare-second",
    )
    conn.commit()
    monkeypatch.setattr(
        "app.oral.get_media_storage",
        lambda _conn: (_ for _ in ()).throw(OSError("storage unavailable")),
    )

    assert run_next_oral_task(conn, worker_id="worker", vendor=vendor) == first.task_id
    monkeypatch.undo()
    transport.on("POST", "/api/v2/hifly/video/create_by_tts", envelope({"task_id": "vendor-2"}))
    assert run_next_oral_task(conn, worker_id="worker", vendor=vendor) == second.task_id

    rows = conn.execute(
        "SELECT id, status, vendor_task_id FROM oral_tasks WHERE id IN (%s, %s)",
        (first.task_id, second.task_id),
    ).fetchall()
    states = {str(row["id"]): (str(row["status"]), row["vendor_task_id"]) for row in rows}
    assert states[first.task_id] == ("SUBMISSION_UNCERTAIN", "vendor-1")
    assert states[second.task_id] == ("RUNNING", "vendor-2")


def test_sqlite_oral_finalize_failure_preserves_vendor_outcome(
    tmp_path: Path,
    fake_source_storage: FakeSourceStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = seed_scene(tmp_path, "oral-finalize-preserve.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()
    transport.on(
        "POST", "/api/v2/hifly/video/create_by_tts", envelope({"task_id": "vendor-accepted"})
    )
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="终结失败",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="sqlite-finalize-preserve",
    )
    monkeypatch.setattr(
        "app.oral.finalize_oral_task_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database failure")),
    )

    assert run_next_oral_task(conn, worker_id="worker", vendor=vendor) == created.task_id

    task = conn.execute(
        "SELECT status, vendor_task_id, reconciliation_json FROM oral_tasks WHERE id = %s",
        (created.task_id,),
    ).fetchone()
    assert tuple(task)[:2] == ("SUBMISSION_UNCERTAIN", "vendor-accepted")
    assert json.loads(task["reconciliation_json"])["vendor_task_id"] == "vendor-accepted"


def test_audio_submit_renews_between_external_steps_and_marks_paid_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_source_storage: FakeSourceStorage,
) -> None:
    conn = seed_scene(tmp_path, "oral-audio-renewal.db")
    avatar_id, _ = seed_ready_assets(conn)
    vendor, transport = make_vendor()

    def read_without_transaction(_key: str) -> bytes:
        assert not conn.raw.in_transaction
        return b"FAKEMEDIA"

    monkeypatch.setattr(fake_source_storage, "get_object", read_without_transaction)
    transport.on(
        "POST",
        "/api/v2/hifly/tool/create_upload_url",
        envelope(
            {
                "upload_url": "https://up.example/audio",
                "content_type": "audio/mpeg",
                "file_id": "audio-file-1",
            }
        ),
    )
    transport.on(
        "POST", "/api/v2/hifly/video/create_by_audio", envelope({"task_id": "audio-video-1"})
    )
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id=None,
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=None,
        mode="AUDIO",
        title="续租口播",
        script_text=None,
        audio_asset_id="asset-audio",
        subtitle=None,
        idempotency_key="audio-renewal",
    )
    renewals = 0
    original = renew_oral_task_lease

    def recording_renewal(*args: Any, **kwargs: Any) -> bool:
        nonlocal renewals
        renewals += 1
        return original(*args, **kwargs)

    monkeypatch.setattr("app.oral.renew_oral_task_lease", recording_renewal)
    run_next_oral_task(conn, worker_id="worker-renewal", vendor=vendor)

    row = conn.execute(
        "SELECT status, vendor_task_id, provider_started_at FROM oral_tasks WHERE id = %s",
        (created.task_id,),
    ).fetchone()
    assert renewals == 4
    assert row["status"] == "RUNNING"
    assert row["vendor_task_id"] == "audio-video-1"
    assert row["provider_started_at"] is not None


def test_oral_lease_renew_and_submit_boundary_reject_expired_or_replaced_token(
    tmp_path: Path,
) -> None:
    conn = seed_scene(tmp_path, "oral-renew-fencing.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="租约围栏",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-renew-fencing",
    )
    lease = acquire_oral_task(conn, worker_id="worker-old")
    assert lease is not None
    assert renew_oral_task_lease(conn, lease=lease)
    assert not conn.raw.in_transaction
    conn.execute(
        "UPDATE oral_tasks SET locked_until = '2020-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()
    assert not renew_oral_task_lease(conn, lease=lease)
    assert not conn.raw.in_transaction
    assert not mark_oral_provider_submission_started(conn, lease=lease)
    assert not conn.raw.in_transaction
    conn.execute(
        "UPDATE oral_tasks SET lease_token = 'replacement-token', "
        "locked_until = '2099-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()
    assert not renew_oral_task_lease(conn, lease=lease)
    assert not conn.raw.in_transaction
    assert not mark_oral_provider_submission_started(conn, lease=lease)
    assert not conn.raw.in_transaction
    row = conn.execute(
        "SELECT provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert row["provider_started_at"] is None


def test_sqlite_provider_started_survives_crash_and_prevents_paid_replay(
    tmp_path: Path,
) -> None:
    conn = seed_scene(tmp_path, "oral-provider-crash.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    vendor, transport = make_vendor()

    def crash_after_acceptance(_body: bytes | None) -> bytes:
        assert not conn.raw.in_transaction
        raise KeyboardInterrupt("worker crashed during paid submit")

    transport.on("POST", "/api/v2/hifly/video/create_by_tts", crash_after_acceptance)
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="崩溃围栏",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key="oral-provider-crash",
    )

    with pytest.raises(KeyboardInterrupt, match="worker crashed"):
        run_next_oral_task(conn, worker_id="worker-crash", vendor=vendor)
    assert not conn.raw.in_transaction
    started = conn.execute(
        "SELECT status, provider_started_at FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert started["status"] == "SUBMITTING"
    assert started["provider_started_at"] is not None

    conn.execute(
        "UPDATE oral_tasks SET locked_until = '2020-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()
    assert acquire_oral_task(conn, worker_id="worker-replacement") is None
    recovered = conn.execute(
        "SELECT status, lease_token FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    assert tuple(recovered) == ("SUBMISSION_UNCERTAIN", None)
    assert (
        sum(
            1
            for method, url in transport.calls
            if method == "POST" and url.endswith("create_by_tts")
        )
        == 1
    )


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
        project_id="project-1",
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
        project_id="project-1",
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
        project_id="project-1",
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
    assert not preserve_oral_task_outcome_for_reconciliation(
        conn,
        lease=lease,
        outcome=OralOutcome(status="RUNNING", vendor_task_id="stale-vendor-task"),
        cause=RuntimeError("finalize failed"),
    )
    task = conn.execute(
        "SELECT status, vendor_task_id, reconciliation_json FROM oral_tasks WHERE id = %s",
        (created.task_id,),
    ).fetchone()
    assert tuple(task)[:2] == ("SUBMITTING", None)
    assert json.loads(task["reconciliation_json"]) == {"submission_contract": 1}
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    assert tuple(wallet) == (9, 1)


@pytest.mark.parametrize("finalizer", ["complete", "fail"])
def test_expired_sqlite_oral_lease_cannot_finalize_or_release_wallet(
    tmp_path: Path,
    finalizer: str,
) -> None:
    conn = seed_scene(tmp_path, f"oral-expired-{finalizer}.db")
    avatar_id, voice_id = seed_ready_assets(conn)
    created = create_oral_task(
        conn,
        actor=actor(),
        project_id="project-1",
        identity_id="ident-1",
        avatar_id=avatar_id,
        voice_id=voice_id,
        mode="TTS",
        title="过期租约",
        script_text="文案",
        audio_asset_id=None,
        subtitle=None,
        idempotency_key=f"oral-expired-{finalizer}",
    )
    lease = acquire_oral_task(conn, worker_id="expired-worker")
    assert lease is not None
    vendor, _ = make_vendor()
    work = prepare_oral_task_work(conn, lease=lease, vendor=vendor)
    conn.execute(
        "UPDATE oral_tasks SET locked_until = '2020-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()

    if finalizer == "complete":
        with pytest.raises(OralDomainError, match="租约"):
            finalize_oral_task_work(conn, work=work, outcome=OralOutcome(status="SUCCEEDED"))
    else:
        assert not fail_claimed_oral_task(conn, lease=lease, cause=RuntimeError("local failure"))

    task = conn.execute(
        "SELECT status, lease_token FROM oral_tasks WHERE id = %s", (created.task_id,)
    ).fetchone()
    wallet = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'employee_1'"
    ).fetchone()
    ledger = conn.execute(
        "SELECT type FROM wallet_transactions WHERE oral_task_id = %s ORDER BY type",
        (created.task_id,),
    ).fetchall()
    assert tuple(task) == ("SUBMITTING", str(lease["lease_token"]))
    assert tuple(wallet) == (9, 1)
    assert [row["type"] for row in ledger] == ["RESERVE"]


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
    assert not preserve_oral_clone_outcome_for_reconciliation(
        conn,
        lease=lease,
        outcome=CloneOutcome(status="RUNNING", vendor_task_id="stale-clone-task"),
        cause=RuntimeError("finalize failed"),
    )
    clone = conn.execute(
        "SELECT status, vendor_task_id, reconciliation_json FROM oral_avatars WHERE id = %s",
        (started.task_id,),
    ).fetchone()
    assert tuple(clone)[:2] == ("SUBMITTING", None)
    assert (
        json.loads(clone["reconciliation_json"])["expected_source_sha256"]
        == hashlib.sha256(b"FAKEMEDIA").hexdigest()
    )


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

    assert result["source_sha256"] == hashlib.sha256(b"FAKEMEDIA").hexdigest()
    metadata = json.loads(
        conn.execute("SELECT metadata_json FROM assets WHERE id = 'asset-auth'").fetchone()[0]
    )
    assert metadata["oral_clone_consents"] == [
        {
            "identity_id": "ident-1",
            "source_asset_id": "asset-src",
            "source_sha256": hashlib.sha256(b"FAKEMEDIA").hexdigest(),
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
        project_id="project-1",
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
    conn.execute(
        "UPDATE oral_tasks SET locked_until = '2020-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()
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
    conn.execute(
        "UPDATE oral_avatars SET locked_until = '2020-01-01T00:00:00+00:00' WHERE id = %s",
        (created.task_id,),
    )
    conn.commit()
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
    assert oral_unit_price_fen(conn, user_id="employee_1") == ORAL_UNIT_PRICE_FEN_DEFAULT == 1000
    conn.execute("UPDATE runtime_settings SET internal_base_unit_price_fen = 750 WHERE id = 1")
    conn.commit()
    assert oral_unit_price_fen(conn, user_id="employee_1") == 750


def test_oral_unit_price_uses_current_user_customer_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = seed_scene(tmp_path, "oral-customer-price.db")
    requested_users: list[str] = []

    def customer_quote(_self, *, user_id: str):
        requested_users.append(user_id)
        return {"charged_unit_price_fen": 625}

    monkeypatch.setattr(
        "app.oral.SettingsRepository.read_customer_billing_settings",
        customer_quote,
    )

    assert oral_unit_price_fen(conn, user_id="employee_1") == 625
    assert requested_users == ["employee_1"]


def test_oral_unit_price_fails_closed_when_settings_are_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = seed_scene(tmp_path, "oral-price-failed.db")
    monkeypatch.setattr(
        "app.oral.SettingsRepository.read_billing_settings",
        lambda _self: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    with pytest.raises(OralDomainError, match="计费配置暂不可用"):
        oral_unit_price_fen(conn, user_id="employee_1")
