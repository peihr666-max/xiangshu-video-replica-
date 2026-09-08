from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.auth import CurrentUser
from app.db_portable import BusinessConnection

TEMPLATES = {"bottom_caption", "center_banner", "top_title"}


class CompositionDomainError(ValueError):
    pass


class CompositionConflictError(CompositionDomainError):
    pass


@dataclass(frozen=True)
class CompositionLease:
    id: str
    owner_user_id: str
    oral_task_id: str
    source_asset_id: str
    source_storage_uri: str
    template: str
    text: str
    worker_id: str
    lease_token: str
    attempt: int


def _dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _request_hash(*, oral_task_id: str, template: str, text: str) -> str:
    payload = json.dumps(
        {"oral_task_id": oral_task_id, "template": template, "text": text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def create_composition(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    oral_task_id: str,
    template: str,
    text: str,
    idempotency_key: str,
) -> dict[str, Any]:
    normalized_text = text.strip()
    if template not in TEMPLATES or not normalized_text:
        raise CompositionDomainError("Invalid composition template or empty text")
    request_hash = _request_hash(oral_task_id=oral_task_id, template=template, text=normalized_text)
    composition_id: str | None = None
    with conn.transaction():
        replay = conn.execute(
            "SELECT * FROM oral_compositions WHERE owner_user_id = %s AND idempotency_key = %s",
            (actor.id, idempotency_key),
        ).fetchone()
        if replay is not None:
            if str(replay["request_hash"]) != request_hash:
                raise CompositionConflictError(
                    "Idempotency key is already bound to another request"
                )
            result = _dict(replay)
            result["replayed"] = True
            return result
        source = conn.execute(
            "SELECT t.owner_user_id, a.id AS asset_id FROM oral_tasks t "
            "JOIN assets a ON a.id = t.result_asset_id "
            "WHERE t.id = %s AND t.status = 'SUCCEEDED' FOR UPDATE",
            (oral_task_id,),
        ).fetchone()
        if source is None or str(source["owner_user_id"]) != actor.id:
            raise CompositionDomainError("Succeeded oral task is not available to this owner")
        next_version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS value FROM oral_compositions "
            "WHERE oral_task_id = %s",
            (oral_task_id,),
        ).fetchone()
        composition_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO oral_compositions (id, owner_user_id, oral_task_id, source_asset_id, "
            "template, text, idempotency_key, request_hash, version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                composition_id,
                actor.id,
                oral_task_id,
                source["asset_id"],
                template,
                normalized_text,
                idempotency_key,
                request_hash,
                next_version["value"],
            ),
        )
    assert composition_id is not None
    row = conn.execute(
        "SELECT * FROM oral_compositions WHERE id = %s", (composition_id,)
    ).fetchone()
    assert row is not None
    result = _dict(row)
    result["replayed"] = False
    return result


def read_composition(
    conn: BusinessConnection, *, actor: CurrentUser, composition_id: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM oral_compositions WHERE id = %s AND owner_user_id = %s",
        (composition_id, actor.id),
    ).fetchone()
    if row is None:
        raise CompositionDomainError("Composition not found")
    return _dict(row)


def list_compositions(
    conn: BusinessConnection, *, actor: CurrentUser, oral_task_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM oral_compositions WHERE oral_task_id = %s AND owner_user_id = %s "
        "ORDER BY version DESC",
        (oral_task_id, actor.id),
    ).fetchall()
    return [_dict(row) for row in rows]


def cancel_composition(
    conn: BusinessConnection, *, actor: CurrentUser, composition_id: str
) -> dict[str, Any]:
    row = read_composition(conn, actor=actor, composition_id=composition_id)
    if row["status"] != "QUEUED":
        raise CompositionConflictError("Only a queued composition can be cancelled")
    updated = conn.execute(
        "UPDATE oral_compositions SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s AND status = 'QUEUED'",
        (composition_id,),
    )
    conn.commit()
    if updated.rowcount != 1:
        raise CompositionConflictError("Composition state changed")
    return read_composition(conn, actor=actor, composition_id=composition_id)


def retry_composition(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    composition_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    retry_id: str | None = None
    with conn.transaction():
        failed = read_composition(conn, actor=actor, composition_id=composition_id)
        if failed["status"] != "FAILED":
            raise CompositionConflictError("Only a failed composition can be retried")
        replay = conn.execute(
            "SELECT * FROM oral_compositions WHERE owner_user_id = %s AND idempotency_key = %s",
            (actor.id, idempotency_key),
        ).fetchone()
        if replay is not None:
            if str(replay["retry_of_id"] or "") != composition_id:
                raise CompositionConflictError(
                    "Idempotency key is already bound to another request"
                )
            result = _dict(replay)
            result["replayed"] = True
            return result
        conn.execute(
            "SELECT id FROM oral_tasks WHERE id = %s FOR UPDATE", (failed["oral_task_id"],)
        )
        next_version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS value FROM oral_compositions "
            "WHERE oral_task_id = %s",
            (failed["oral_task_id"],),
        ).fetchone()
        retry_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO oral_compositions (id, owner_user_id, oral_task_id, source_asset_id, "
            "template, text, idempotency_key, request_hash, version, retry_of_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                retry_id,
                actor.id,
                failed["oral_task_id"],
                failed["source_asset_id"],
                failed["template"],
                failed["text"],
                idempotency_key,
                failed["request_hash"],
                next_version["value"],
                composition_id,
            ),
        )
    assert retry_id is not None
    result = read_composition(conn, actor=actor, composition_id=retry_id)
    result["replayed"] = False
    return result


def claim_composition(conn: BusinessConnection, *, worker_id: str) -> CompositionLease | None:
    now = datetime.now(UTC)
    now_text = now.isoformat()
    expires = (now + timedelta(seconds=300)).isoformat()
    with conn:
        conn.execute(
            "UPDATE oral_compositions SET status = 'QUEUED', locked_by = NULL, "
            "lease_token = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'RUNNING' AND locked_until IS NOT NULL "
            "AND locked_until::timestamptz <= %s",
            (now_text,),
        )
        row = conn.execute(
            "SELECT c.*, a.storage_uri FROM oral_compositions c "
            "JOIN assets a ON a.id = c.source_asset_id WHERE c.status = 'QUEUED' "
            "ORDER BY c.created_at, c.id LIMIT 1 FOR UPDATE SKIP LOCKED"
        ).fetchone()
        if row is None:
            return None
        lease_token = uuid.uuid4().hex
        updated = conn.execute(
            "UPDATE oral_compositions SET status = 'RUNNING', locked_by = %s, lease_token = %s, "
            "locked_until = %s, attempt = attempt + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s AND status = 'QUEUED'",
            (worker_id, lease_token, expires, row["id"]),
        )
        if updated.rowcount != 1:
            return None
    return CompositionLease(
        id=str(row["id"]),
        owner_user_id=str(row["owner_user_id"]),
        oral_task_id=str(row["oral_task_id"]),
        source_asset_id=str(row["source_asset_id"]),
        source_storage_uri=str(row["storage_uri"]),
        template=str(row["template"]),
        text=str(row["text"]),
        worker_id=worker_id,
        lease_token=lease_token,
        attempt=int(row["attempt"]) + 1,
    )


def fail_composition(
    conn: BusinessConnection, *, lease: CompositionLease, error_message: str
) -> None:
    conn.execute(
        "UPDATE oral_compositions SET status = 'FAILED', error_message = %s, locked_by = NULL, "
        "lease_token = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s AND status = 'RUNNING' AND locked_by = %s "
        "AND lease_token = %s AND attempt = %s",
        (error_message[:500], lease.id, lease.worker_id, lease.lease_token, lease.attempt),
    )
    conn.commit()


def complete_composition(
    conn: BusinessConnection,
    *,
    lease: CompositionLease,
    storage_uri: str,
    sha256: str,
    size_bytes: int,
) -> str:
    asset_id = str(uuid.uuid4())
    with conn:
        current = conn.execute(
            "SELECT status, locked_by, lease_token, attempt, version "
            "FROM oral_compositions WHERE id = %s FOR UPDATE",
            (lease.id,),
        ).fetchone()
        if (
            current is None
            or current["status"] != "RUNNING"
            or current["locked_by"] != lease.worker_id
            or current["lease_token"] != lease.lease_token
            or int(current["attempt"]) != lease.attempt
        ):
            raise CompositionConflictError("Composition lease was lost")
        conn.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
            "content_type, created_by_user_id) VALUES "
            "(%s, NULL, 'oral_composed_video', %s, %s, %s, 'video/mp4', %s)",
            (asset_id, storage_uri, sha256, size_bytes, lease.owner_user_id),
        )
        newer_active = conn.execute(
            "SELECT 1 FROM oral_compositions WHERE oral_task_id = %s AND is_active = 1 "
            "AND version > %s LIMIT 1",
            (lease.oral_task_id, current["version"]),
        ).fetchone()
        activate = newer_active is None
        if activate:
            conn.execute(
                "UPDATE oral_compositions SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE oral_task_id = %s AND is_active = 1",
                (lease.oral_task_id,),
            )
        conn.execute(
            "UPDATE oral_compositions SET status = 'SUCCEEDED', result_asset_id = %s, "
            "is_active = %s, error_message = NULL, locked_by = NULL, lease_token = NULL, "
            "locked_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (asset_id, 1 if activate else 0, lease.id),
        )
    return asset_id
