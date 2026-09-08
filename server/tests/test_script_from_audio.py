"""工作台"提取文案"（script-from-audio）管线合同。

锁定的关键行为：
- 幂等提交与项目级并发互斥（409）；
- 审计/权限（auditor 禁写、跨项目禁读）；
- Worker 全链：取原视频 → 抽音轨（测试注入）→ 临时对象上传 → ASR →
  **临时音频即删**（成功与失败终态都无残留）；
- 转写全文进 result_json，绝不写生成门禁管制的脚本版本表；
- ffmpeg/ffprobe 缺失时任务 fail-closed 并给出可读错误。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.asr import AsrProviderError, FakeAsrProvider, TranscriptResult
from app.auth import get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.generation_worker import run_worker_once
from app.main import app
from app.script_from_audio import ProviderTaskCheckpointResult
from app.storage import FakeStorageAdapter


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[Path]:
    db_path = tmp_path / "script-from-audio.db"
    with initialize_database(db_path) as conn:
        seed_data(conn)
    yield db_path


@pytest.fixture()
def client(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("VIDEO_REPLICA_DB_PATH", str(db_path))
    monkeypatch.setenv("VIDEO_REPLICA_ASR_PROVIDER", "fake")

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
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
        ("project_owned", "employee_1", "Owned Project"),
    )
    for asset_id in ("asset_video", "asset_video_2"):
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256, size_bytes,
                content_type, created_by_user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                "project_owned",
                "reference_video",
                f"fake://private-bucket/projects/project_owned/uploads/{asset_id}/src.mp4",
                "",
                0,
                "video/mp4",
                "employee_1",
            ),
        )


def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Dev-User-Id": user_id}


def enqueue(client: TestClient, **overrides: str) -> object:
    body = {"source_asset_id": "asset_video"}
    body.update(overrides)
    return client.post(
        "/api/projects/project_owned/script-from-audio",
        json=body,
        headers=auth_headers("employee_1"),
    )


class StubMediaTools:
    """测试注入：替换 ffmpeg 抽取与 ffprobe 探测，避免依赖真实二进制。"""

    def __init__(self) -> None:
        self.extracted: list[Path] = []
        self.probed: list[Path] = []

    def extract_audio(self, ffmpeg_path: str, video_path: Path, audio_path: Path) -> None:
        self.extracted.append(video_path)
        audio_path.write_bytes(b"fake-audio-bytes")

    def probe_duration_seconds(self, ffprobe_path: str, media_path: Path) -> float | None:
        self.probed.append(media_path)
        return 12.5


@pytest.fixture()
def stub_media(monkeypatch: pytest.MonkeyPatch) -> StubMediaTools:
    stub = StubMediaTools()
    import app.script_from_audio as domain

    monkeypatch.setattr(domain, "extract_audio", stub.extract_audio)
    monkeypatch.setattr(domain, "probe_duration_seconds", stub.probe_duration_seconds)
    monkeypatch.setattr(domain, "resolve_media_binary", lambda tool: f"/stub/{tool}")
    return stub


def test_download_intent_failure_removes_uploaded_temporary_audio(
    stub_media: StubMediaTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.script_from_audio import PreparedScriptFromAudio, prepare_script_from_audio_submission

    storage = FakeStorageAdapter(provider="fake", bucket="private-bucket")
    source_key = "projects/project-1/uploads/asset-1/source.mp4"
    storage.put_object(source_key, b"video", content_type="video/mp4")
    original_error = RuntimeError("signing unavailable")
    monkeypatch.setattr(
        storage,
        "create_download_intent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(original_error),
    )
    work = PreparedScriptFromAudio(
        task_id="task-1",
        project_id="project-1",
        asset_id="asset-1",
        object_key=source_key,
        storage=storage,
        asr=FakeAsrProvider(),
        ffmpeg_path="/stub/ffmpeg",
        ffprobe_path="/stub/ffprobe",
    )

    with pytest.raises(RuntimeError) as caught:
        prepare_script_from_audio_submission(work)

    assert caught.value is original_error
    assert not any(key.startswith("tmp/asr/") for key in storage._objects)


def test_cleanup_failure_does_not_replace_download_intent_error(
    stub_media: StubMediaTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.script_from_audio import PreparedScriptFromAudio, prepare_script_from_audio_submission

    storage = FakeStorageAdapter(provider="fake", bucket="private-bucket")
    source_key = "projects/project-1/uploads/asset-1/source.mp4"
    storage.put_object(source_key, b"video", content_type="video/mp4")
    original_error = RuntimeError("signing unavailable")
    monkeypatch.setattr(
        storage,
        "create_download_intent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(original_error),
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup unavailable")),
    )
    work = PreparedScriptFromAudio(
        task_id="task-1",
        project_id="project-1",
        asset_id="asset-1",
        object_key=source_key,
        storage=storage,
        asr=FakeAsrProvider(),
        ffmpeg_path="/stub/ffmpeg",
        ffprobe_path="/stub/ffprobe",
    )

    with pytest.raises(RuntimeError) as caught:
        prepare_script_from_audio_submission(work)

    assert caught.value is original_error


def test_enqueue_returns_202_and_replays_idempotently(client: TestClient) -> None:
    first = enqueue(client)
    assert first.status_code == 202
    created = first.json()
    assert created["status"] == "PENDING"
    assert created["result"] is None

    # 同内容的新提交按设计返回同一个活跃任务。
    replay = enqueue(client)
    assert replay.status_code == 202
    assert replay.json()["id"] == created["id"]

    # 内容变化的新提交撞上活跃任务 → 409。
    conflict = enqueue(client, source_asset_id="asset_video_2")
    assert conflict.status_code == 409

    with_idem = client.post(
        "/api/projects/project_owned/script-from-audio",
        json={"source_asset_id": "asset_video", "idempotency_key": "key-1"},
        headers=auth_headers("employee_1"),
    )
    assert with_idem.status_code == 202
    replayed = client.post(
        "/api/projects/project_owned/script-from-audio",
        json={"source_asset_id": "asset_video", "idempotency_key": "key-1"},
        headers=auth_headers("employee_1"),
    )
    assert replayed.status_code == 202
    assert replayed.json()["id"] == with_idem.json()["id"]


def test_auditor_cannot_enqueue(client: TestClient) -> None:
    response = client.post(
        "/api/projects/project_owned/script-from-audio",
        json={"source_asset_id": "asset_video"},
        headers=auth_headers("auditor_1"),
    )
    assert response.status_code == 403


def test_other_user_cannot_read_task(client: TestClient) -> None:
    created = enqueue(client)
    task_id = created.json()["id"]
    forbidden = client.get(
        f"/api/script-from-audio-tasks/{task_id}",
        headers=auth_headers("employee_2"),
    )
    # 非本项目成员按"不存在"隐藏（仓库权限语义），而非 403。
    assert forbidden.status_code == 404
    allowed = client.get(
        f"/api/script-from-audio-tasks/{task_id}",
        headers=auth_headers("employee_1"),
    )
    assert allowed.status_code == 200


def test_worker_pipeline_completes_and_deletes_temp_audio(
    client: TestClient, db_path: Path, stub_media: StubMediaTools
) -> None:
    created = enqueue(client)
    task_id = created.json()["id"]

    storage = FakeStorageAdapter(provider="fake", bucket="private-bucket")
    storage.put_object(
        "projects/project_owned/uploads/asset_video/src.mp4",
        b"fake-video-bytes",
        content_type="video/mp4",
    )
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        processed = run_worker_once(
            conn,
            worker_id="audio-test-worker",
            storage=storage,
            max_tasks=1,
        )
    assert processed == 1
    assert len(stub_media.extracted) == 1

    task = client.get(
        f"/api/script-from-audio-tasks/{task_id}", headers=auth_headers("employee_1")
    ).json()
    assert task["status"] == "SUCCEEDED"
    assert task["result"]["text"].startswith("（测试转写）")
    assert task["result"]["duration_sec"] == pytest.approx(12.5)

    # 转写用完即删：存储中不存在任何 tmp/asr 残留。
    leftovers = [key for key in storage._objects if key.startswith("tmp/asr/")]
    assert leftovers == []
    # 生成门禁的脚本版本表未被触碰。
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM versions").fetchone()
    assert int(count["n"]) == 0


def test_latest_endpoint_returns_newest_task(client: TestClient) -> None:
    assert (
        client.get(
            "/api/projects/project_owned/script-from-audio-tasks/latest",
            headers=auth_headers("employee_1"),
        ).json()
        is None
    )
    enqueue(client)
    latest = client.get(
        "/api/projects/project_owned/script-from-audio-tasks/latest",
        headers=auth_headers("employee_1"),
    )
    assert latest.status_code == 200
    assert latest.json()["status"] in ("PENDING", "RUNNING", "SUCCEEDED")


def test_ambiguous_provider_failure_preserves_reconciliation_state(
    client: TestClient, db_path: Path, stub_media: StubMediaTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.generation_worker as worker_module
    import app.script_from_audio as domain

    def failing_transcribe(file_url, *, duration_sec=None, on_task_created=None):
        assert on_task_created is not None
        on_task_created("provider-before-poll-failure")
        raise AsrProviderError("语音转写服务返回错误（HTTP 500）")

    created = enqueue(client)
    task_id = created.json()["id"]
    storage = FakeStorageAdapter(provider="fake", bucket="private-bucket")
    storage.put_object(
        "projects/project_owned/uploads/asset_video/src.mp4",
        b"fake-video-bytes",
        content_type="video/mp4",
    )

    original_prepare = domain.prepare_script_from_audio_task

    def prepare_with_failing_asr(conn, *, lease, **kwargs):
        work = original_prepare(conn, lease=lease, storage=storage)
        work.asr = type(
            "FailingAsr",
            (),
            {"transcribe": staticmethod(failing_transcribe)},
        )()
        return work

    monkeypatch.setattr(worker_module, "prepare_script_from_audio_task", prepare_with_failing_asr)

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        run_worker_once(conn, worker_id="audio-test-worker", storage=storage, max_tasks=1)

    task = client.get(
        f"/api/script-from-audio-tasks/{task_id}", headers=auth_headers("employee_1")
    ).json()
    assert task["status"] == "SUBMISSION_UNCERTAIN"
    assert task["retryable"] is False
    assert "语音转写" in (task["error_message"] or "")
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        row = conn.execute(
            "SELECT provider_task_id FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
    assert row["provider_task_id"] == "provider-before-poll-failure"
    leftovers = [key for key in storage._objects if key.startswith("tmp/asr/")]
    assert leftovers == []


def test_definite_provider_rejection_fails_without_allowing_ambiguous_replay(
    client: TestClient,
    db_path: Path,
) -> None:
    from app.script_from_audio import (
        acquire_script_from_audio_task,
        fail_script_from_audio_task,
        mark_script_from_audio_submission_started,
    )

    task_id = enqueue(client).json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        lease = acquire_script_from_audio_task(conn, worker_id="audio-definite")
        assert lease is not None
        mark_script_from_audio_submission_started(conn, lease=lease)
        assert fail_script_from_audio_task(
            conn,
            lease=lease,
            cause=AsrProviderError(
                "语音转写任务被供应商拒绝",
                submission_uncertain=False,
                provider_task_id="provider-rejected-1",
            ),
            submission_started=True,
        )
        row = conn.execute(
            "SELECT status, retryable, provider_task_id FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()

    assert row["status"] == "FAILED"
    assert row["retryable"] == 0
    assert row["provider_task_id"] == "provider-rejected-1"


def test_ambiguous_submission_blocks_duplicate_project_charge(
    client: TestClient,
    db_path: Path,
) -> None:
    from app.script_from_audio import (
        acquire_script_from_audio_task,
        fail_script_from_audio_task,
        mark_script_from_audio_submission_started,
    )

    task_id = enqueue(client, idempotency_key="uncertain-key").json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        lease = acquire_script_from_audio_task(conn, worker_id="audio-uncertain")
        assert lease is not None
        mark_script_from_audio_submission_started(conn, lease=lease)
        assert fail_script_from_audio_task(
            conn,
            lease=lease,
            cause=AsrProviderError(
                "轮询传输超时",
                provider_task_id="provider-uncertain-1",
            ),
            submission_started=True,
        )

    replay = enqueue(client, idempotency_key="uncertain-key")
    assert replay.status_code == 202
    assert replay.json()["id"] == task_id
    duplicate = enqueue(client, source_asset_id="asset_video_2")
    assert duplicate.status_code == 409

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        row = conn.execute(
            "SELECT status, retryable, provider_task_id FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert row["retryable"] == 0
    assert row["provider_task_id"] == "provider-uncertain-1"


def test_missing_ffmpeg_fails_closed(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.generation_worker as worker_module
    import app.script_from_audio as domain
    from app.media_tools import MediaToolUnavailable

    created = enqueue(client)
    task_id = created.json()["id"]
    storage = FakeStorageAdapter(provider="fake", bucket="private-bucket")
    storage.put_object(
        "projects/project_owned/uploads/asset_video/src.mp4",
        b"fake-video-bytes",
        content_type="video/mp4",
    )

    def unavailable(tool: str) -> str:
        raise MediaToolUnavailable("未找到 ffmpeg")

    original_prepare = domain.prepare_script_from_audio_task

    def prepare_without_tools(conn, *, lease, **kwargs):
        saved = domain.resolve_media_binary
        domain.resolve_media_binary = unavailable
        try:
            return original_prepare(conn, lease=lease, storage=storage)
        finally:
            domain.resolve_media_binary = saved

    monkeypatch.setattr(worker_module, "prepare_script_from_audio_task", prepare_without_tools)

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        run_worker_once(conn, worker_id="audio-test-worker", storage=storage, max_tasks=1)

    task = client.get(
        f"/api/script-from-audio-tasks/{task_id}", headers=auth_headers("employee_1")
    ).json()
    assert task["status"] == "FAILED"
    assert "未找到 ffmpeg" in (task["error_message"] or "")


def test_local_preparation_failure_does_not_mark_provider_started(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.generation_worker as worker_module

    task_id = enqueue(client).json()["id"]
    storage = FakeStorageAdapter(provider="fake", bucket="private-bucket")

    def fail_locally(_work):
        raise RuntimeError("local ffmpeg failed")

    monkeypatch.setattr(worker_module, "prepare_script_from_audio_submission", fail_locally)
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        run_worker_once(conn, worker_id="audio-local-failure", storage=storage, max_tasks=1)
        row = conn.execute(
            "SELECT status, provider_started_at, retryable "
            "FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
    assert row["status"] == "FAILED"
    assert row["provider_started_at"] is None
    assert row["retryable"] == 1


def test_transcript_result_dataclass_defaults() -> None:
    result = TranscriptResult(text="abc", duration_sec=None, language=None)
    assert result.text == "abc"


def test_pg_worker_consumes_script_from_audio_without_db_during_external_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.generation_worker as worker
    from app.script_from_audio import ScriptFromAudioTaskLease

    lease = ScriptFromAudioTaskLease(
        id="audio-task-1",
        project_id="project-1",
        created_by_user_id="user-1",
        worker_id="pg-worker",
        lease_token="lease-token-1",
        attempt=1,
    )
    transaction_depth = 0
    steps: list[str] = []
    fake_conn = object()

    @contextmanager
    def fake_pg_transaction():
        nonlocal transaction_depth
        transaction_depth += 1
        try:
            yield object()
        finally:
            transaction_depth -= 1

    monkeypatch.setattr(worker, "pg_transaction", fake_pg_transaction)
    monkeypatch.setattr(
        worker.BusinessConnection,
        "postgres",
        staticmethod(lambda _raw: fake_conn),
    )
    for name in (
        "acquire_generation_continuation_lease",
        "acquire_generation_task_lease",
        "acquire_character_generation_task",
        "acquire_analysis_task",
        "acquire_script_rewrite_task",
    ):
        monkeypatch.setattr(worker, name, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        worker,
        "acquire_script_from_audio_task",
        lambda *_args, **_kwargs: lease,
    )

    def prepare(*_args, **_kwargs):
        assert transaction_depth == 1
        steps.append("prepare")
        return object()

    def mark(*_args, **_kwargs):
        assert transaction_depth == 1
        steps.append("mark")
        return True

    def prepare_submission(_work):
        assert transaction_depth == 0
        steps.append("local")
        return object()

    def perform_provider(_work, *, on_task_created):
        assert transaction_depth == 0
        on_task_created("provider-pg-1")
        steps.append("provider")
        return TranscriptResult(text="PG transcript", duration_sec=None, language=None)

    def record(*_args, **kwargs):
        assert transaction_depth == 1
        assert kwargs["provider_task_id"] == "provider-pg-1"
        steps.append("persist")
        return True

    def complete(*_args, **_kwargs):
        assert transaction_depth == 1
        steps.append("complete")
        return True

    monkeypatch.setattr(worker, "prepare_script_from_audio_task", prepare)
    monkeypatch.setattr(worker, "prepare_script_from_audio_submission", prepare_submission)
    monkeypatch.setattr(worker, "mark_script_from_audio_submission_started", mark)
    monkeypatch.setattr(worker, "perform_script_from_audio_provider_call", perform_provider)
    monkeypatch.setattr(worker, "record_script_from_audio_provider_task", record)
    monkeypatch.setattr(worker, "complete_script_from_audio_task", complete)

    processed = worker.run_pg_worker_once(
        worker_id="pg-worker",
        storage=FakeStorageAdapter(provider="fake", bucket="bucket"),
        max_tasks=1,
    )
    assert processed == 1
    assert steps == ["prepare", "local", "mark", "persist", "provider", "complete"]


def test_provider_task_id_survives_worker_crash_and_lease_expiry(
    client: TestClient,
    db_path: Path,
) -> None:
    from app.script_from_audio import (
        acquire_script_from_audio_task,
        mark_script_from_audio_submission_started,
        record_script_from_audio_provider_task,
    )

    task_id = enqueue(client).json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        lease = acquire_script_from_audio_task(conn, worker_id="crashing-worker")
        assert lease is not None
        mark_script_from_audio_submission_started(conn, lease=lease)
        record_script_from_audio_provider_task(
            conn,
            lease=lease,
            provider_task_id="provider-survives-crash",
        )
        conn.execute(
            "UPDATE script_from_audio_tasks SET locked_until = %s WHERE id = %s",
            ((datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"), task_id),
        )
        conn.commit()

        assert acquire_script_from_audio_task(conn, worker_id="replacement-worker") is None
        row = conn.execute(
            "SELECT status, provider_task_id, lease_token "
            "FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()

    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert row["provider_task_id"] == "provider-survives-crash"
    assert row["lease_token"] is None


def test_sweeper_then_observer_backfills_id_once_but_old_attempt_cannot_overwrite(
    client: TestClient,
    db_path: Path,
) -> None:
    from app.script_from_audio import (
        acquire_script_from_audio_task,
        mark_script_from_audio_submission_started,
        record_script_from_audio_provider_task,
    )

    task_id = enqueue(client).json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        old_lease = acquire_script_from_audio_task(conn, worker_id="slow-worker")
        assert old_lease is not None
        mark_script_from_audio_submission_started(conn, lease=old_lease)
        conn.execute(
            "UPDATE script_from_audio_tasks SET locked_until = %s WHERE id = %s",
            ((datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"), task_id),
        )
        conn.commit()
        assert acquire_script_from_audio_task(conn, worker_id="sweeper") is None

        result = record_script_from_audio_provider_task(
            conn,
            lease=old_lease,
            provider_task_id="provider-after-sweep",
        )
        assert result is ProviderTaskCheckpointResult.LATE_UNCERTAIN
        row = conn.execute(
            "SELECT status, attempt, provider_task_id FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
        assert row["status"] == "SUBMISSION_UNCERTAIN"
        assert row["provider_task_id"] == "provider-after-sweep"

        with pytest.raises(HTTPException):
            record_script_from_audio_provider_task(
                conn,
                lease=old_lease,
                provider_task_id="provider-overwrite",
            )
        assert (
            conn.execute(
                "SELECT provider_task_id FROM script_from_audio_tasks WHERE id = %s",
                (task_id,),
            ).fetchone()["provider_task_id"]
            == "provider-after-sweep"
        )

        conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET status = 'PENDING', provider_task_id = NULL, provider_started_at = NULL,
                completed_at = NULL, error_code = NULL, error_message_redacted = NULL
            WHERE id = %s
            """,
            (task_id,),
        )
        conn.commit()
        new_lease = acquire_script_from_audio_task(conn, worker_id="new-attempt")
        assert new_lease is not None
        assert new_lease.attempt == old_lease.attempt + 1
        mark_script_from_audio_submission_started(conn, lease=new_lease)

        with pytest.raises(HTTPException):
            record_script_from_audio_provider_task(
                conn,
                lease=old_lease,
                provider_task_id="provider-old-attempt",
            )
        assert (
            conn.execute(
                "SELECT provider_task_id FROM script_from_audio_tasks WHERE id = %s",
                (task_id,),
            ).fetchone()["provider_task_id"]
            is None
        )


def test_stale_lease_cannot_overwrite_persisted_provider_task_id(
    client: TestClient,
    db_path: Path,
) -> None:
    from app.script_from_audio import (
        acquire_script_from_audio_task,
        mark_script_from_audio_submission_started,
        record_script_from_audio_provider_task,
    )

    task_id = enqueue(client).json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        lease = acquire_script_from_audio_task(conn, worker_id="original-worker")
        assert lease is not None
        mark_script_from_audio_submission_started(conn, lease=lease)
        record_script_from_audio_provider_task(
            conn,
            lease=lease,
            provider_task_id="provider-original",
        )
        conn.execute(
            "UPDATE script_from_audio_tasks SET lease_token = %s WHERE id = %s",
            ("replacement-token", task_id),
        )
        conn.commit()

        with pytest.raises(HTTPException) as error:
            record_script_from_audio_provider_task(
                conn,
                lease=lease,
                provider_task_id="provider-stale-overwrite",
            )
        row = conn.execute(
            "SELECT provider_task_id FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()

    assert error.value.status_code == 409
    assert row["provider_task_id"] == "provider-original"


def test_replacement_lease_token_blocks_all_old_worker_lifecycle_writes(
    client: TestClient,
    db_path: Path,
) -> None:
    from app.script_from_audio import (
        acquire_script_from_audio_task,
        complete_script_from_audio_task,
        fail_script_from_audio_task,
        mark_script_from_audio_submission_started,
    )

    task_id = enqueue(client).json()["id"]
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        old_lease = acquire_script_from_audio_task(conn, worker_id="worker-reused")
        assert old_lease is not None
        expired = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE script_from_audio_tasks SET locked_until = %s WHERE id = %s",
            (expired, task_id),
        )
        conn.commit()
        replacement = acquire_script_from_audio_task(conn, worker_id="worker-reused")
        assert replacement is not None
        assert replacement.lease_token != old_lease.lease_token
        assert replacement.attempt == old_lease.attempt + 1

        with pytest.raises(HTTPException) as mark_error:
            mark_script_from_audio_submission_started(conn, lease=old_lease)
        assert mark_error.value.status_code == 409
        mark_script_from_audio_submission_started(conn, lease=replacement)

        with pytest.raises(HTTPException) as complete_error:
            complete_script_from_audio_task(
                conn,
                lease=old_lease,
                result=TranscriptResult(text="stale result", duration_sec=None, language=None),
            )
        assert complete_error.value.status_code == 409
        assert not fail_script_from_audio_task(
            conn,
            lease=old_lease,
            cause=AsrProviderError(
                "stale ambiguous failure",
                provider_task_id="stale-provider-task",
            ),
            submission_started=True,
        )

        row = conn.execute(
            "SELECT status, attempt, lease_token, result_json, error_code, provider_task_id "
            "FROM script_from_audio_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
        assert row["status"] == "RUNNING"
        assert row["attempt"] == replacement.attempt
        assert row["lease_token"] == replacement.lease_token
        assert row["result_json"] is None
        assert row["error_code"] is None
        assert row["provider_task_id"] is None
