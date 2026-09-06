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
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.asr import AsrProviderError, TranscriptResult
from app.auth import get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.generation_worker import run_worker_once
from app.main import app
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


def test_worker_failures_delete_temp_audio_and_surface_error(
    client: TestClient, db_path: Path, stub_media: StubMediaTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.generation_worker as worker_module
    import app.script_from_audio as domain

    def failing_transcribe(file_url, *, duration_sec=None):
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
    assert task["status"] == "FAILED"
    assert "语音转写" in (task["error_message"] or "")
    leftovers = [key for key in storage._objects if key.startswith("tmp/asr/")]
    assert leftovers == []


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


def test_transcript_result_dataclass_defaults() -> None:
    result = TranscriptResult(text="abc", duration_sec=None, language=None)
    assert result.text == "abc"
