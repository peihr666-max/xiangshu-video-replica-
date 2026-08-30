from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.script_rewrite as script_rewrite
from app.auth import get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.generation_worker import run_worker_once
from app.main import app
from app.settings import SETTINGS_KEY_ENV, SettingsRepository
from app.storage import FakeStorageAdapter


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[Path]:
    db_path = tmp_path / "script-rewrite.db"
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


def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Dev-User-Id": user_id}


def configure_deepseek(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(SETTINGS_KEY_ENV, key)
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        SettingsRepository(conn, fernet=Fernet(key.encode("ascii"))).save_provider_config(
            "deepseek",
            {"api_key": "deepseek-test-key"},
            actor_user_id="employee_1",
        )


def test_script_rewrite_requires_deepseek_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the repo functional without touching the local OS keystore.
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(SETTINGS_KEY_ENV, key)

    response = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("employee_1"),
        json={"text": "原始口播稿内容。"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "DEEPSEEK_NOT_CONFIGURED"


def test_script_rewrite_rejects_empty_text(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_deepseek(db_path, monkeypatch)

    response = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("employee_1"),
        json={"text": "   "},
    )

    assert response.status_code == 422


def test_script_rewrite_denies_other_projects_and_auditors(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_deepseek(db_path, monkeypatch)

    foreign = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("employee_2"),
        json={"text": "原始口播稿内容。"},
    )
    auditor = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("auditor_1"),
        json={"text": "原始口播稿内容。"},
    )

    assert foreign.status_code in (403, 404)
    assert auditor.status_code == 403


def test_script_rewrite_returns_rewritten_text(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_deepseek(db_path, monkeypatch)
    provider_calls: list[str] = []

    def rewrite(**kwargs: str) -> str:
        provider_calls.append(kwargs["source_text"])
        return "这是全新的二创口播稿。"

    monkeypatch.setattr(
        script_rewrite,
        "_request_deepseek",
        rewrite,
    )

    response = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("employee_1"),
        json={"text": "原始口播稿内容，需要被改写。"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert response.json()["result"] is None
    assert provider_calls == []

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        processed = run_worker_once(
            conn,
            worker_id="script-rewrite-test-worker",
            storage=FakeStorageAdapter(provider="fake", bucket="private-bucket"),
            max_tasks=1,
        )
    assert processed == 1
    assert provider_calls == ["原始口播稿内容，需要被改写。"]

    task = client.get(
        f"/api/script-rewrite-tasks/{response.json()['id']}",
        headers=auth_headers("employee_1"),
    )
    assert task.status_code == 200
    payload = task.json()
    assert payload["status"] == "SUCCEEDED"
    assert payload["result"] == {
        "rewritten_text": "这是全新的二创口播稿。",
        "provider": "deepseek",
        "model": "deepseek-chat",
    }

    latest = client.get(
        "/api/projects/project_owned/script-rewrite-tasks/latest",
        headers=auth_headers("employee_1"),
    )
    assert latest.status_code == 200
    assert latest.json()["id"] == response.json()["id"]


def test_expired_provider_submission_becomes_uncertain_without_recalling_provider(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_deepseek(db_path, monkeypatch)
    queued = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("employee_1"),
        json={"text": "不能重复计费的原始口播稿。"},
    )
    assert queued.status_code == 202

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        lease = script_rewrite.acquire_script_rewrite_task(
            conn,
            worker_id="crashed-worker",
        )
        assert lease is not None
        script_rewrite.prepare_script_rewrite_task(conn, lease=lease)
        script_rewrite.mark_script_rewrite_submission_started(conn, lease=lease)
        conn.execute(
            "UPDATE script_rewrite_tasks SET locked_until = %s WHERE id = %s",
            ("2000-01-01 00:00:00", lease.id),
        )
        conn.commit()

        replacement = script_rewrite.acquire_script_rewrite_task(
            conn,
            worker_id="replacement-worker",
        )
        assert replacement is None

    task = client.get(
        f"/api/script-rewrite-tasks/{queued.json()['id']}",
        headers=auth_headers("employee_1"),
    )
    assert task.json()["status"] == "SUBMISSION_UNCERTAIN"
    assert task.json()["retryable"] is False


def test_network_timeout_after_submission_is_not_automatically_retried(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_deepseek(db_path, monkeypatch)
    monkeypatch.setattr(
        script_rewrite,
        "_request_deepseek",
        lambda **_kwargs: (_ for _ in ()).throw(
            HTTPException(
                504,
                detail={
                    "code": "DEEPSEEK_NETWORK_FAILED",
                    "message": "连接 AI 改写服务失败，请检查网络后重试。",
                },
            )
        ),
    )
    queued = client.post(
        "/api/projects/project_owned/script-rewrite",
        headers=auth_headers("employee_1"),
        json={"text": "网络超时的原始口播稿。"},
    )
    assert queued.status_code == 202

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        assert (
            run_worker_once(
                conn,
                worker_id="timeout-worker",
                storage=FakeStorageAdapter(provider="fake", bucket="private-bucket"),
                max_tasks=1,
            )
            == 1
        )
        assert (
            script_rewrite.acquire_script_rewrite_task(
                conn,
                worker_id="second-worker",
            )
            is None
        )

    task = client.get(
        f"/api/script-rewrite-tasks/{queued.json()['id']}",
        headers=auth_headers("employee_1"),
    )
    assert task.json()["status"] == "SUBMISSION_UNCERTAIN"
