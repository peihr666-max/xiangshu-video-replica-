"""Studio notification preferences (C10b: GET/PUT /api/studio/notification-preferences).

个人中心「通知偏好」开关的持久化：按用户一行 JSON 偏好（当前唯一键
enabled），未写入过的用户按服务端默认（开启）返回，不落行。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.main import app


def prefs_client(tmp_path: Path, monkeypatch, db_name: str) -> tuple[TestClient, Path]:
    db_path = tmp_path / db_name
    with initialize_database(db_path) as connection:
        connection.executemany(
            "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
            [
                ("employee_1", "employee_1", "Employee One", "employee"),
                ("employee_2", "employee_2", "Employee Two", "employee"),
            ],
        )
        connection.commit()
    monkeypatch.setenv("VIDEO_REPLICA_DB_PATH", str(db_path))

    def database_override():
        conn = BusinessConnection.sqlite(connect_database(db_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_database] = database_override
    return TestClient(app), db_path


def stored_row_count(db_path: Path, user_id: str) -> int:
    raw = sqlite3.connect(db_path)
    try:
        return int(
            raw.execute(
                "SELECT count(*) FROM studio_notification_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )
    finally:
        raw.close()


def test_get_returns_default_true_without_stored_row(tmp_path: Path, monkeypatch) -> None:
    client, _ = prefs_client(tmp_path, monkeypatch, "prefs-default.db")
    try:
        response = client.get(
            "/api/studio/notification-preferences",
            headers={"X-Dev-User-Id": "employee_1"},
        )
        assert response.status_code == 200
        assert response.json() == {"enabled": True}
    finally:
        app.dependency_overrides.clear()


def test_put_persists_and_get_round_trips(tmp_path: Path, monkeypatch) -> None:
    client, db_path = prefs_client(tmp_path, monkeypatch, "prefs-roundtrip.db")
    try:
        headers = {"X-Dev-User-Id": "employee_1"}
        saved = client.put(
            "/api/studio/notification-preferences",
            headers=headers,
            json={"enabled": False},
        )
        assert saved.status_code == 200
        assert saved.json() == {"enabled": False}

        again = client.put(
            "/api/studio/notification-preferences",
            headers=headers,
            json={"enabled": True},
        )
        assert again.status_code == 200
        assert again.json() == {"enabled": True}

        # upsert：同一用户只有一行，不因重复保存而堆积。
        assert stored_row_count(db_path, "employee_1") == 1
        assert client.get("/api/studio/notification-preferences", headers=headers).json() == {
            "enabled": True
        }
    finally:
        app.dependency_overrides.clear()


def test_preferences_are_scoped_per_user(tmp_path: Path, monkeypatch) -> None:
    client, _ = prefs_client(tmp_path, monkeypatch, "prefs-scoped.db")
    try:
        client.put(
            "/api/studio/notification-preferences",
            headers={"X-Dev-User-Id": "employee_1"},
            json={"enabled": False},
        )
        assert client.get(
            "/api/studio/notification-preferences",
            headers={"X-Dev-User-Id": "employee_1"},
        ).json() == {"enabled": False}
        # 另一个用户不受影响，仍为默认值。
        assert client.get(
            "/api/studio/notification-preferences",
            headers={"X-Dev-User-Id": "employee_2"},
        ).json() == {"enabled": True}
    finally:
        app.dependency_overrides.clear()


def test_put_rejects_unknown_fields(tmp_path: Path, monkeypatch) -> None:
    client, _ = prefs_client(tmp_path, monkeypatch, "prefs-invalid.db")
    try:
        response = client.put(
            "/api/studio/notification-preferences",
            headers={"X-Dev-User-Id": "employee_1"},
            json={"enabled": True, "marketing": True},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
