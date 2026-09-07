from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_database
from app.db import connect_database, initialize_database
from app.db_portable import BusinessConnection
from app.main import app
from app.materials import (
    material_final_storage_key,
    persist_material_upload,
    prepare_material_upload,
    probe_material_upload,
)
from app.media_routes import get_media_storage
from app.storage import FakeStorageAdapter, LocalStorageAdapter


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "materials.db"
    with initialize_database(path) as conn:
        seed_materials(conn)
    yield path


@pytest.fixture()
def storage() -> FakeStorageAdapter:
    return FakeStorageAdapter(provider="fake", bucket="private-bucket")


@pytest.fixture()
def client(
    db_path: Path,
    storage: FakeStorageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("VIDEO_REPLICA_DB_PATH", str(db_path))

    def database_override() -> Iterator[BusinessConnection]:
        conn = BusinessConnection.sqlite(connect_database(db_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_database] = database_override
    app.dependency_overrides[get_media_storage] = lambda: storage
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def auth_headers(user_id: str = "employee_1") -> dict[str, str]:
    return {"X-Dev-User-Id": user_id}


def seed_materials(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, ?)",
        [
            ("employee_1", "employee_1", "Employee One", "employee"),
            ("employee_2", "employee_2", "Employee Two", "employee"),
            ("auditor_1", "auditor_1", "Auditor One", "auditor"),
            ("admin_1", "admin_1", "Admin One", "admin"),
        ],
    )
    conn.executemany(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
        [
            ("project-owned", "employee_1", "自有项目"),
            ("project-other", "employee_2", "他人项目"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, metadata_json, created_by_user_id
        ) VALUES (?, ?, 'reference_video', ?, ?, 8, 'video/mp4', '{}', ?)
        """,
        [
            (
                "asset-owned",
                "project-owned",
                "fake://private-bucket/projects/project-owned/source.mp4",
                "a" * 64,
                "employee_1",
            ),
            (
                "asset-other",
                "project-other",
                "fake://private-bucket/projects/project-other/source.mp4",
                "b" * 64,
                "employee_2",
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO generation_batches (
            id, project_id, created_by_user_id, idempotency_key,
            request_hash, request_snapshot_json, status, display_name
        ) VALUES ('batch-direct', 'project-owned', 'employee_1', 'idem-direct',
                  'hash-direct', '{}', 'SUCCEEDED', '直出成片')
        """
    )
    conn.execute(
        """
        INSERT INTO generation_tasks (
            id, batch_id, provider, model, status, archive_status,
            provider_result_url, completed_at
        ) VALUES ('task-direct', 'batch-direct', 'metaso', 'h3', 'SUCCEEDED',
                  'DIRECT', 'https://provider.example/result.mp4', CURRENT_TIMESTAMP)
        """
    )
    conn.commit()


def test_lists_owned_stored_and_direct_materials_with_server_pagination(
    client: TestClient,
) -> None:
    first = client.get(
        "/api/studio/materials?page=1&page_size=1",
        headers=auth_headers(),
    )
    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert len(first.json()["items"]) == 1

    second = client.get(
        "/api/studio/materials?page=2&page_size=1",
        headers=auth_headers(),
    )
    ids = {first.json()["items"][0]["id"], second.json()["items"][0]["id"]}
    assert ids == {"asset:asset-owned", "generation:task-direct"}
    assert all(item["owner_user_id"] == "employee_1" for item in first.json()["items"])


def test_direct_result_is_visible_but_not_presented_as_cloud_asset(client: TestClient) -> None:
    response = client.get(
        "/api/studio/materials?source=generation",
        headers=auth_headers(),
    )
    assert response.status_code == 200
    material = response.json()["items"][0]
    assert material == {
        **material,
        "id": "generation:task-direct",
        "asset_id": None,
        "generation_task_id": "task-direct",
        "delivery": "direct",
        "status": "ready",
        "saved": False,
    }
    assert material["allowed_uses"] == []
    assert "preview" in material["allowed_actions"]
    assert "rename" not in material["allowed_actions"]


def test_archived_generation_result_keeps_generation_identity_and_cloud_actions(
    client: TestClient, db_path: Path
) -> None:
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256, size_bytes,
                content_type, metadata_json, created_by_user_id
            ) VALUES ('archived-video', 'project-owned', 'generation_video',
                      'fake://private-bucket/generation-results/task-direct.mp4',
                      ?, 16, 'video/mp4', '{}', 'employee_1')
            """,
            ("c" * 64,),
        )
        conn.execute(
            """
            UPDATE generation_tasks
            SET archive_status = 'ARCHIVED', result_asset_id = 'archived-video'
            WHERE id = 'task-direct'
            """
        )
        conn.commit()

    response = client.get(
        "/api/studio/materials?source=generation",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    material = response.json()["items"][0]
    assert material["id"] == "asset:archived-video"
    assert material["asset_id"] == "archived-video"
    assert material["generation_task_id"] == "task-direct"
    assert material["group"] == "任务结果"
    assert material["delivery"] == "stored"
    assert material["saved"] is True
    assert "download" in material["allowed_actions"]


def test_upload_audio_to_storage_then_complete_and_list_it(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={
            "filename": "讲解.mp3",
            "content_type": "audio/mpeg",
            "size_bytes": 11,
            "title": "完整口播音频",
            "group": "口播素材",
        },
    )
    assert intent.status_code == 200
    body = intent.json()
    assert body["material_id"] == f"asset:{body['asset_id']}"
    assert body["storage_key"].startswith("materials/employee_1/")
    assert body["storage_key"].endswith("/upload.mp3")

    original_content = b"ID3abcdefgh"
    storage.put_object(body["storage_key"], original_content, content_type="audio/mpeg")
    completed = client.post(
        f"/api/studio/materials/uploads/{body['asset_id']}/complete",
        headers=auth_headers(),
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "ready"
    assert completed.json()["size_bytes"] == 11
    digest = hashlib.sha256(original_content).hexdigest()
    final_key = f"materials/employee_1/{body['asset_id']}/original-{digest}.mp3"
    assert storage.get_object(final_key) == original_content
    assert storage.head_object(body["storage_key"]) is None

    # A still-valid pre-signed upload URL can only rewrite the staging key.
    storage.put_object(body["storage_key"], b"ID3replaced", content_type="audio/mpeg")
    repeated = client.post(
        f"/api/studio/materials/uploads/{body['asset_id']}/complete",
        headers=auth_headers(),
    )
    assert repeated.status_code == 200
    assert storage.get_object(final_key) == original_content
    with connect_database(db_path) as conn:
        row = conn.execute(
            "SELECT storage_uri, sha256 FROM assets WHERE id = ?",
            (body["asset_id"],),
        ).fetchone()
    assert row is not None
    assert str(row["storage_uri"]).endswith(final_key)
    assert str(row["sha256"]) == digest

    listed = client.get(
        "/api/studio/materials?media_type=audio",
        headers=auth_headers(),
    )
    assert listed.status_code == 200
    material = listed.json()["items"][0]
    assert material["title"] == "完整口播音频"
    assert material["allowed_uses"] == ["oral_audio"]
    assert material["delivery"] == "stored"
    assert material["saved"] is True


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("notes.txt", "text/plain"),
        ("fake.mp3", "video/mp4"),
        ("fake.png", "audio/mpeg"),
    ],
)
def test_upload_intent_rejects_unsupported_or_mismatched_media(
    client: TestClient,
    filename: str,
    content_type: str,
) -> None:
    response = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": 10,
        },
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "MATERIAL_TYPE_UNSUPPORTED"


def test_rename_hide_and_resolve_hidden_material(
    client: TestClient,
    db_path: Path,
) -> None:
    renamed = client.patch(
        "/api/studio/materials/asset:asset-owned",
        headers=auth_headers(),
        json={"title": "新的素材名称", "group": "重点参考"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "新的素材名称"
    assert renamed.json()["group"] == "重点参考"
    with connect_database(db_path) as conn:
        action = conn.execute(
            "SELECT action FROM audit_logs WHERE action = 'studio.material.update'"
        ).fetchone()
    assert action is not None

    hidden = client.delete(
        "/api/studio/materials/asset:asset-owned",
        headers=auth_headers(),
    )
    assert hidden.status_code == 204
    listed = client.get("/api/studio/materials", headers=auth_headers())
    assert "asset:asset-owned" not in {item["id"] for item in listed.json()["items"]}

    resolved = client.post(
        "/api/studio/materials/resolve",
        headers=auth_headers(),
        json={"material_ids": ["asset:asset-owned", "asset:asset-other", "asset:missing"]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["items"][0]["id"] == "asset:asset-owned"
    assert resolved.json()["items"][0]["hidden"] is True
    assert resolved.json()["unavailable_ids"] == ["asset:asset-other", "asset:missing"]


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_auditor_cannot_change_material_library(
    client: TestClient,
    method: str,
) -> None:
    response = getattr(client, method)(
        "/api/studio/materials/asset:asset-owned",
        headers=auth_headers("auditor_1"),
        **({"json": {"title": "审计员不得修改"}} if method == "patch" else {}),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ROLE_FORBIDDEN"


def test_complete_rejects_bytes_that_do_not_match_declared_media(
    client: TestClient,
    storage: FakeStorageAdapter,
) -> None:
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={
            "filename": "voice.mp3",
            "content_type": "audio/mpeg",
            "size_bytes": 12,
        },
    ).json()
    storage.put_object(intent["storage_key"], b"not an audio", content_type="audio/mpeg")

    response = client.post(
        f"/api/studio/materials/uploads/{intent['asset_id']}/complete",
        headers=auth_headers(),
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "MATERIAL_CONTENT_INVALID"


def test_complete_rechecks_size_after_reading_the_staging_object(
    client: TestClient,
    storage: FakeStorageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={"filename": "voice.mp3", "content_type": "audio/mpeg", "size_bytes": 3},
    ).json()
    storage.put_object(intent["storage_key"], b"ID3", content_type="audio/mpeg")
    monkeypatch.setattr(storage, "get_object", lambda key: b"ID3changed")

    response = client.post(
        f"/api/studio/materials/uploads/{intent['asset_id']}/complete",
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MATERIAL_SIZE_MISMATCH"


def test_two_prepared_completions_keep_the_first_committed_content_key(
    client: TestClient,
    db_path: Path,
    storage: FakeStorageAdapter,
) -> None:
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={"filename": "voice.mp3", "content_type": "audio/mpeg", "size_bytes": 4},
    ).json()
    actor = CurrentUser(
        id="employee_1",
        username="employee_1",
        display_name="Employee One",
        role="employee",
    )
    storage.put_object(intent["storage_key"], b"ID3A", content_type="audio/mpeg")
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        prepared_a = prepare_material_upload(conn, actor=actor, asset_id=intent["asset_id"])
    probed_a = probe_material_upload(prepared_a, storage=storage)

    storage.put_object(intent["storage_key"], b"ID3B", content_type="audio/mpeg")
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        prepared_b = prepare_material_upload(conn, actor=actor, asset_id=intent["asset_id"])
    probed_b = probe_material_upload(prepared_b, storage=storage)
    key_a = material_final_storage_key(prepared_a, sha256=probed_a.sha256)
    key_b = material_final_storage_key(prepared_b, sha256=probed_b.sha256)
    stored_a = storage.put_object(key_a, probed_a.content, content_type="audio/mpeg")
    stored_b = storage.put_object(key_b, probed_b.content, content_type="audio/mpeg")

    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        _, committed_a = persist_material_upload(
            conn,
            actor=actor,
            probed=replace(probed_a, storage_uri=stored_a.uri),
        )
    with BusinessConnection.sqlite(connect_database(db_path)) as conn:
        _, committed_b = persist_material_upload(
            conn,
            actor=actor,
            probed=replace(probed_b, storage_uri=stored_b.uri),
        )

    assert committed_a == stored_a.uri
    assert committed_b == stored_a.uri
    assert committed_b != stored_b.uri


def test_local_material_upload_uses_authenticated_api_endpoint(
    client: TestClient,
    tmp_path: Path,
) -> None:
    local = LocalStorageAdapter(root=tmp_path / "objects", bucket="local-private")
    app.dependency_overrides[get_media_storage] = lambda: local
    content = b"\x89PNG\r\n\x1a\nbody"
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={
            "filename": "庭院.png",
            "content_type": "image/png",
            "size_bytes": len(content),
        },
    )
    assert intent.status_code == 200
    body = intent.json()
    assert body["url"].endswith(f"/api/studio/materials/uploads/{body['asset_id']}/content")

    uploaded = client.put(
        f"/api/studio/materials/uploads/{body['asset_id']}/content",
        headers={**auth_headers(), "Content-Type": "image/png"},
        content=content,
    )
    assert uploaded.status_code == 204
    completed = client.post(
        f"/api/studio/materials/uploads/{body['asset_id']}/complete",
        headers=auth_headers(),
    )
    assert completed.status_code == 200
    assert completed.json()["saved"] is True
    replaced = client.put(
        f"/api/studio/materials/uploads/{body['asset_id']}/content",
        headers={**auth_headers(), "Content-Type": "image/png"},
        content=content,
    )
    assert replaced.status_code == 409
    assert replaced.json()["detail"]["code"] == "MATERIAL_UPLOAD_ALREADY_COMPLETED"


@pytest.mark.parametrize("role", ["employee", "customer"])
@pytest.mark.parametrize("user_id", ["employee_1", "employee_2"])
def test_list_and_resolve_never_grant_access_through_foreign_preferences(
    client: TestClient, db_path: Path, role: str, user_id: str
) -> None:
    own_id = "asset:asset-owned" if user_id == "employee_1" else "asset:asset-other"
    foreign_id = "asset:asset-other" if user_id == "employee_1" else "asset:asset-owned"
    with connect_database(db_path) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.execute(
            """
            INSERT INTO studio_material_preferences (
                user_id, source_type, source_id, title_override
            ) VALUES (?, 'asset', ?, '不得授权的偏好')
            """,
            (user_id, foreign_id.removeprefix("asset:")),
        )

    listed = client.get("/api/studio/materials", headers=auth_headers(user_id))
    assert listed.status_code == 200
    assert all(item["owner_user_id"] == user_id for item in listed.json()["items"])
    assert own_id in {item["id"] for item in listed.json()["items"]}
    resolved = client.post(
        "/api/studio/materials/resolve",
        headers=auth_headers(user_id),
        json={"material_ids": [own_id, foreign_id, "generation:task-direct"]},
    )
    assert resolved.status_code == 200
    assert all(item["owner_user_id"] == user_id for item in resolved.json()["items"])
    assert foreign_id in resolved.json()["unavailable_ids"]
    if user_id == "employee_2":
        assert "generation:task-direct" in resolved.json()["unavailable_ids"]


@pytest.mark.parametrize("role", ["employee", "customer"])
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_other_user_cannot_rename_or_hide_material(
    client: TestClient, db_path: Path, role: str, method: str
) -> None:
    with connect_database(db_path) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = 'employee_2'", (role,))
    response = getattr(client, method)(
        "/api/studio/materials/asset:asset-owned",
        headers=auth_headers("employee_2"),
        **({"json": {"title": "不得覆盖", "hidden": True}} if method == "patch" else {}),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MATERIAL_NOT_FOUND"
    with connect_database(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM studio_material_preferences").fetchone()[0] == 0


def test_auditor_material_actions_match_read_only_endpoints(client: TestClient) -> None:
    listed = client.get("/api/studio/materials", headers=auth_headers("auditor_1"))
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 3
    for item in items:
        assert item["allowed_uses"] == []
        # Stored previews use download-url, which is forbidden to auditors.
        assert item["allowed_actions"] == (["preview"] if item["delivery"] == "direct" else [])
    resolved = client.post(
        "/api/studio/materials/resolve",
        headers=auth_headers("auditor_1"),
        json={"material_ids": [item["id"] for item in items]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["items"] == items
    upload = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers("auditor_1"),
        json={"filename": "voice.mp3", "content_type": "audio/mpeg", "size_bytes": 3},
    )
    assert upload.status_code == 403
    download = client.post(
        "/api/assets/asset-owned/download-url", headers=auth_headers("auditor_1")
    )
    assert download.status_code == 403


def test_admin_can_manage_other_users_material_preferences(client: TestClient) -> None:
    listed = client.get("/api/studio/materials", headers=auth_headers("admin_1"))
    assert listed.status_code == 200
    assert listed.json()["total"] == 3
    stored = next(item for item in listed.json()["items"] if item["id"] == "asset:asset-other")
    assert stored["allowed_actions"] == ["preview", "download", "rename", "hide"]
    renamed = client.patch(
        "/api/studio/materials/asset:asset-other",
        headers=auth_headers("admin_1"),
        json={"title": "管理员视图名称"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "管理员视图名称"
    hidden = client.delete(
        "/api/studio/materials/asset:asset-other", headers=auth_headers("admin_1")
    )
    assert hidden.status_code == 204
    owner_view = client.get("/api/studio/materials", headers=auth_headers("employee_2"))
    assert owner_view.json()["items"][0]["title"] == "他人项目"
    assert owner_view.json()["items"][0]["hidden"] is False


def test_admin_foreign_audio_is_visible_but_not_advertised_for_generation(
    client: TestClient, db_path: Path
) -> None:
    with connect_database(db_path) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256, size_bytes,
                content_type, metadata_json, created_by_user_id
            ) VALUES ('foreign-audio', 'project-other', 'audio',
                      'fake://private-bucket/projects/project-other/audio.mp3',
                      'audio-hash', 8, 'audio/mpeg', '{}', 'employee_2')
            """
        )

    admin = client.get("/api/studio/materials?media_type=audio", headers=auth_headers("admin_1"))
    owner = client.get("/api/studio/materials?media_type=audio", headers=auth_headers("employee_2"))

    assert admin.status_code == 200
    assert admin.json()["items"][0]["allowed_uses"] == []
    assert owner.status_code == 200
    assert owner.json()["items"][0]["allowed_uses"] == ["oral_audio"]


@pytest.mark.parametrize(
    ("user_id", "role"),
    [
        ("admin_1", "admin"),
        ("auditor_1", "auditor"),
        ("employee_2", "employee"),
        ("employee_2", "customer"),
    ],
)
def test_only_upload_creator_can_complete_or_replace_uploaded_bytes(
    client: TestClient, db_path: Path, tmp_path: Path, user_id: str, role: str
) -> None:
    with connect_database(db_path) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    local = LocalStorageAdapter(root=tmp_path / "objects", bucket="local-private")
    app.dependency_overrides[get_media_storage] = lambda: local
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={"filename": "voice.mp3", "content_type": "audio/mpeg", "size_bytes": 3},
    ).json()
    local.put_object(intent["storage_key"], b"ID3", content_type="audio/mpeg")
    expected_status = 403 if user_id == "auditor_1" else 404
    completed = client.post(
        f"/api/studio/materials/uploads/{intent['asset_id']}/complete",
        headers=auth_headers(user_id),
    )
    assert completed.status_code == expected_status
    replaced = client.put(
        f"/api/studio/materials/uploads/{intent['asset_id']}/content",
        headers={**auth_headers(user_id), "Content-Type": "audio/mpeg"},
        content=b"ID4",
    )
    assert replaced.status_code == expected_status
    assert local.get_object(intent["storage_key"]) == b"ID3"
    with connect_database(db_path) as conn:
        row = conn.execute(
            "SELECT size_bytes, sha256, created_by_user_id FROM assets WHERE id = ?",
            (intent["asset_id"],),
        ).fetchone()
    assert tuple(row) == (0, "", "employee_1")


@pytest.mark.parametrize("role", ["employee", "customer"])
def test_private_uploaded_materials_are_isolated_in_every_library_operation(
    client: TestClient, db_path: Path, role: str
) -> None:
    with connect_database(db_path) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = 'employee_2'", (role,))
    intent = client.post(
        "/api/studio/materials/upload-intent",
        headers=auth_headers(),
        json={"filename": "private.mp3", "content_type": "audio/mpeg", "size_bytes": 3},
    ).json()
    material_id = intent["material_id"]
    foreign_headers = auth_headers("employee_2")
    listed = client.get("/api/studio/materials?source=upload", headers=foreign_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 0
    resolved = client.post(
        "/api/studio/materials/resolve",
        headers=foreign_headers,
        json={"material_ids": [material_id]},
    )
    assert resolved.status_code == 200
    assert resolved.json() == {"items": [], "unavailable_ids": [material_id]}
    renamed = client.patch(
        f"/api/studio/materials/{material_id}",
        headers=foreign_headers,
        json={"title": "不得覆盖"},
    )
    assert renamed.status_code == 404
    hidden = client.delete(f"/api/studio/materials/{material_id}", headers=foreign_headers)
    assert hidden.status_code == 404


@pytest.mark.parametrize("role", ["employee", "customer", "admin"])
def test_material_uses_only_advertise_completed_audio_workflow(
    client: TestClient, db_path: Path, storage: FakeStorageAdapter, role: str
) -> None:
    with connect_database(db_path) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = 'employee_1'", (role,))
    for filename, content_type, content in (
        ("voice.mp3", "audio/mpeg", b"ID3"),
        ("frame.png", "image/png", b"\x89PNG\r\n\x1a\nbody"),
        ("video.mp4", "video/mp4", b"\x00\x00\x00\x14ftypisom"),
    ):
        intent = client.post(
            "/api/studio/materials/upload-intent",
            headers=auth_headers(),
            json={"filename": filename, "content_type": content_type, "size_bytes": len(content)},
        ).json()
        pending = client.post(
            "/api/studio/materials/resolve",
            headers=auth_headers(),
            json={"material_ids": [intent["material_id"]]},
        ).json()["items"][0]
        assert pending["allowed_uses"] == []
        upload_key = intent.get("storage_key") or unquote(urlsplit(intent["url"]).path.lstrip("/"))
        storage.put_object(upload_key, content, content_type=content_type)
        completed = client.post(
            f"/api/studio/materials/uploads/{intent['asset_id']}/complete",
            headers=auth_headers(),
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["allowed_uses"] == (
            ["oral_audio"] if filename.endswith("mp3") else []
        )


def test_project_audio_without_hash_is_not_advertised_for_oral_use(
    client: TestClient, db_path: Path
) -> None:
    with connect_database(db_path) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256, size_bytes,
                content_type, metadata_json, created_by_user_id
            ) VALUES ('unfinished-audio', 'project-owned', 'audio',
                      'fake://private-bucket/projects/project-owned/audio.mp3',
                      '', 8, 'audio/mpeg', '{}', 'employee_1')
            """
        )

    response = client.get(
        "/api/studio/materials?media_type=audio",
        headers=auth_headers("employee_1"),
    )

    assert response.status_code == 200
    material = response.json()["items"][0]
    assert material["id"] == "asset:unfinished-audio"
    assert material["status"] == "uploading"
    assert material["allowed_uses"] == []
