from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.auth import CurrentUser
from app.db import initialize_database
from app.db_portable import BusinessConnection
from app.permissions import require_asset_access


def _actor(user_id: str) -> CurrentUser:
    return CurrentUser(id=user_id, username=user_id, display_name=user_id, role="employee")


def test_oral_result_asset_is_readable_only_by_task_owner(tmp_path: Path) -> None:
    sqlite_conn = initialize_database(tmp_path / "oral-result-permissions.db")
    conn = BusinessConnection.sqlite(sqlite_conn)
    for user_id in ("owner", "other"):
        conn.execute(
            "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, 'employee')",
            (user_id, user_id, user_id),
        )
    conn.execute(
        """
        INSERT INTO person_identities (id, owner_user_id, display_name, status)
        VALUES ('identity', 'owner', 'Owner', 'ACTIVE')
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES ('oral-result', NULL, 'oral_video', 'local://oral/result.mp4',
                  'result-hash', 12, 'video/mp4', 'owner')
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES ('owned-audio', NULL, 'oral_audio', 'local://oral/input.mp3',
                  'audio-hash', 10, 'audio/mpeg', 'owner')
        """
    )
    conn.execute(
        """
        INSERT INTO oral_avatars (
            id, identity_id, owner_user_id, title, vendor_avatar_id,
            status, source_kind, source_asset_id
        ) VALUES ('avatar', 'identity', 'owner', 'Avatar', 'vendor-avatar',
                  'READY', 'VIDEO', 'source')
        """
    )
    conn.execute(
        """
        INSERT INTO oral_tasks (
            id, owner_user_id, identity_id, avatar_id, mode, title, status,
            result_asset_id, estimated_cost_fen, idempotency_key
        ) VALUES ('task', 'owner', 'identity', 'avatar', 'TTS', 'Result',
                  'SUCCEEDED', 'oral-result', 1000, 'oral-result-permissions')
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES ('unlinked', NULL, 'misc', 'local://misc/unlinked.bin',
                  'misc-hash', 8, 'application/octet-stream', 'owner')
        """
    )
    conn.commit()

    row = require_asset_access(
        conn, actor=_actor("owner"), asset_id="oral-result", action="asset.read"
    )
    assert row["id"] == "oral-result"
    audio = require_asset_access(
        conn, actor=_actor("owner"), asset_id="owned-audio", action="asset.read"
    )
    assert audio["id"] == "owned-audio"

    for actor_id, asset_id in (
        ("other", "oral-result"),
        ("other", "owned-audio"),
        ("owner", "unlinked"),
    ):
        with pytest.raises(HTTPException) as error:
            require_asset_access(
                conn, actor=_actor(actor_id), asset_id=asset_id, action="asset.read"
            )
        assert error.value.status_code == 404
        assert error.value.detail["code"] == "ASSET_NOT_FOUND"
