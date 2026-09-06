"""Durable oral-media worker operations.

Claims and final database writes are short transactions. Provider and object
storage calls happen only in ``perform_oral_work`` between those transactions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyError, HiflySubmissionUncertain
from app.internal_billing import finalize_oral_billing
from app.media import storage_key_from_uri
from app.storage import StorageAdapter, StoredObject

logger = logging.getLogger(__name__)

OralWorkKind = Literal[
    "avatar_submit",
    "avatar_poll",
    "voice_submit",
    "voice_poll",
    "task_submit",
    "task_poll",
    "task_archive",
]
OralOutcome = Literal["submitted", "waiting", "uncertain", "failed", "ready", "archive"]


@dataclass(frozen=True)
class OralWorkLease:
    kind: OralWorkKind
    record_id: str
    worker_id: str
    row: dict[str, Any]


@dataclass(frozen=True)
class OralWorkResult:
    outcome: OralOutcome
    provider_task_id: str | None = None
    provider_resource_id: str | None = None
    provider_result_url: str | None = None
    duration_sec: int | None = None
    stored: StoredObject | None = None
    message: str | None = None


class OralLeaseLostError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _claim_row(
    conn: BusinessConnection,
    *,
    table: str,
    record_id: str,
    worker_id: str,
    current_state_sql: str,
    current_state_params: tuple[object, ...],
    assignments: str,
    lease_expires_at: str,
) -> bool:
    cursor = conn.execute(
        f"""
        UPDATE {table}
        SET {assignments}, lease_owner = %s, lease_expires_at = %s,
            attempt_count = attempt_count + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND ({current_state_sql})
          AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
        """,  # noqa: S608 - table/assignments are fixed internal literals
        (
            worker_id,
            lease_expires_at,
            record_id,
            *current_state_params,
            _iso(_now()),
        ),
    )
    return cursor.rowcount == 1


def _quarantine_expired_submissions(conn: BusinessConnection, now: str) -> None:
    for table in ("oral_avatars", "oral_voices"):
        conn.execute(
            f"""
            UPDATE {table}
            SET submission_state = 'SUBMISSION_UNKNOWN', lease_owner = NULL,
                lease_expires_at = NULL, error_message = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE submission_state = 'SUBMITTING' AND lease_expires_at <= %s
            """,  # noqa: S608 - fixed table names
            ("供应商提交结果未知，已停止自动重试", now),
        )
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'SUBMISSION_UNCERTAIN', submission_state = 'SUBMISSION_UNKNOWN',
            lease_owner = NULL, lease_expires_at = NULL,
            error_message = %s, updated_at = CURRENT_TIMESTAMP
        WHERE status = 'SUBMITTING' AND lease_expires_at <= %s
        """,
        ("供应商提交结果未知，已停止自动重试", now),
    )
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'ARCHIVE_FAILED', lease_owner = NULL, lease_expires_at = NULL,
            next_attempt_at = NULL, error_message = %s, updated_at = CURRENT_TIMESTAMP
        WHERE status = 'ARCHIVING' AND lease_expires_at <= %s
        """,
        ("成片归档中断，可安全重试归档", now),
    )


def claim_oral_work(
    conn: BusinessConnection,
    *,
    worker_id: str,
    lease_seconds: int = 120,
) -> OralWorkLease | None:
    """Claim one oral operation with CAS; expired paid submissions quarantine."""
    now = _now()
    now_text = _iso(now)
    expires = _iso(now + timedelta(seconds=lease_seconds))
    with conn:
        _quarantine_expired_submissions(conn, now_text)

        task = conn.execute(
            """
            SELECT * FROM oral_tasks
            WHERE status IN ('ARCHIVING', 'RUNNING', 'QUEUED')
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
              AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
            ORDER BY CASE status WHEN 'ARCHIVING' THEN 0 WHEN 'RUNNING' THEN 1 ELSE 2 END,
                     created_at, id
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (now_text, now_text),
        ).fetchone()
        if task is not None:
            row = dict(task)
            status = str(row["status"])
            kind: OralWorkKind = {
                "QUEUED": "task_submit",
                "RUNNING": "task_poll",
                "ARCHIVING": "task_archive",
            }[status]
            assignments = (
                "status = 'SUBMITTING', submission_state = 'SUBMITTING'"
                if status == "QUEUED"
                else "status = status"
            )
            if _claim_row(
                conn,
                table="oral_tasks",
                record_id=str(row["id"]),
                worker_id=worker_id,
                current_state_sql="status = %s",
                current_state_params=(status,),
                assignments=assignments,
                lease_expires_at=expires,
            ):
                row["status"] = "SUBMITTING" if status == "QUEUED" else status
                return OralWorkLease(kind, str(row["id"]), worker_id, row)

        for table, prefix in (("oral_avatars", "avatar"), ("oral_voices", "voice")):
            candidate = conn.execute(
                f"""
                SELECT * FROM {table}
                WHERE (
                    submission_state = 'LOCAL_PENDING'
                    OR (submission_state = 'SUBMITTED' AND status = 'RUNNING')
                )
                  AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                  AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                ORDER BY CASE submission_state WHEN 'SUBMITTED' THEN 0 ELSE 1 END,
                         created_at, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,  # noqa: S608 - fixed table names
                (now_text, now_text),
            ).fetchone()
            if candidate is None:
                continue
            row = dict(candidate)
            submitting = str(row["submission_state"]) == "LOCAL_PENDING"
            kind = f"{prefix}_{'submit' if submitting else 'poll'}"
            if _claim_row(
                conn,
                table=table,
                record_id=str(row["id"]),
                worker_id=worker_id,
                current_state_sql="submission_state = %s AND status = %s",
                current_state_params=(
                    str(row["submission_state"]),
                    str(row["status"]),
                ),
                assignments=(
                    "submission_state = 'SUBMITTING'"
                    if submitting
                    else "submission_state = submission_state"
                ),
                lease_expires_at=expires,
            ):
                return OralWorkLease(
                    kind=kind,  # type: ignore[arg-type]
                    record_id=str(row["id"]),
                    worker_id=worker_id,
                    row=row,
                )
    return None


def _object_bytes(storage: StorageAdapter, uri: str) -> bytes:
    return storage.get_object(storage_key_from_uri(uri))


def perform_oral_work(
    lease: OralWorkLease,
    *,
    vendor: HiflyClient,
    storage: StorageAdapter,
) -> OralWorkResult:
    """Perform provider/storage I/O with no database transaction."""
    row = lease.row
    try:
        if lease.kind in {"avatar_submit", "voice_submit", "task_submit"}:
            return _perform_submission(lease, vendor=vendor, storage=storage)
        if lease.kind == "avatar_poll":
            snapshot = vendor.avatar_task(str(row["vendor_task_id"]))
            if snapshot.status == "DONE" and snapshot.avatar_id:
                return OralWorkResult("ready", provider_resource_id=snapshot.avatar_id)
            if snapshot.status == "FAILED":
                return OralWorkResult("failed", message="分身制作未通过")
            return OralWorkResult("waiting")
        if lease.kind == "voice_poll":
            snapshot = vendor.voice_task(str(row["vendor_task_id"]))
            if snapshot.status == "DONE" and snapshot.voice and snapshot.demo_url:
                demo = vendor.download(snapshot.demo_url)
                if not demo:
                    return OralWorkResult("waiting")
                stored = storage.put_object(
                    f"oral/voices/{lease.record_id}/demo.mp3",
                    demo,
                    content_type="audio/mpeg",
                )
                return OralWorkResult(
                    "ready", provider_resource_id=snapshot.voice, stored=stored
                )
            if snapshot.status == "FAILED":
                return OralWorkResult("failed", message="声音克隆未通过")
            return OralWorkResult("waiting")
        if lease.kind == "task_poll":
            snapshot = vendor.video_task(str(row["vendor_task_id"]))
            if snapshot.status == "DONE" and snapshot.video_url:
                return OralWorkResult(
                    "archive",
                    provider_result_url=snapshot.video_url,
                    duration_sec=snapshot.duration,
                )
            if snapshot.status == "FAILED":
                return OralWorkResult("failed", message="数字人服务生成失败")
            return OralWorkResult("waiting")
        if lease.kind == "task_archive":
            result_url = str(row["provider_result_url"] or "")
            if not result_url:
                return OralWorkResult("failed", message="口播成片地址缺失")
            content = vendor.download(result_url)
            stored = storage.put_object(
                f"oral/results/{lease.record_id}.mp4",
                content,
                content_type="video/mp4",
            )
            return OralWorkResult("ready", stored=stored)
    except HiflySubmissionUncertain as exc:
        return OralWorkResult("uncertain", message=str(exc)[:500])
    except HiflyError as exc:
        if lease.kind.endswith("submit"):
            return OralWorkResult("failed", message=str(exc)[:500])
        return OralWorkResult("waiting", message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001 - storage/provider boundary
        logger.warning("oral worker operation failed: kind=%s error=%s", lease.kind, type(exc).__name__)
        if lease.kind == "task_archive":
            return OralWorkResult("failed", message="口播成片归档失败")
        if lease.kind.endswith("submit"):
            return OralWorkResult("uncertain", message="口播任务提交结果未知")
        return OralWorkResult("waiting")
    raise AssertionError(f"unsupported oral work kind: {lease.kind}")


def _perform_submission(
    lease: OralWorkLease,
    *,
    vendor: HiflyClient,
    storage: StorageAdapter,
) -> OralWorkResult:
    row = lease.row
    if lease.kind == "avatar_submit":
        content = _object_bytes(storage, str(row["source_storage_uri"]))
        extension = "png" if str(row["source_kind"]) == "IMAGE" else "mp4"
        target = vendor.create_upload_url(extension)
        vendor.upload_file(target, content)
        creator = (
            vendor.create_avatar_by_image
            if str(row["source_kind"]) == "IMAGE"
            else vendor.create_avatar_by_video
        )
        task_id = creator(
            title=str(row["title"])[:20], file_id=target.file_id, aigc_flag=True
        )
        return OralWorkResult("submitted", provider_task_id=task_id)
    if lease.kind == "voice_submit":
        content = _object_bytes(storage, str(row["source_storage_uri"]))
        target = vendor.create_upload_url("mp3")
        vendor.upload_file(target, content)
        task_id = vendor.create_voice(title=str(row["title"])[:20], file_id=target.file_id)
        return OralWorkResult("submitted", provider_task_id=task_id)
    if str(row["mode"]) == "TTS":
        task_id = vendor.create_video_by_tts(
            voice=str(row["vendor_voice_id"]),
            text=str(row["script_text"]),
            avatar=str(row["vendor_avatar_id"]),
            title=str(row["title"])[:20],
            aigc_flag=True,
            subtitle=(json.loads(str(row["subtitle_json"])) if row["subtitle_json"] else None),
        )
    else:
        content = _object_bytes(storage, str(row["audio_storage_uri"]))
        target = vendor.create_upload_url("mp3")
        vendor.upload_file(target, content)
        task_id = vendor.create_video_by_audio(
            avatar=str(row["vendor_avatar_id"]),
            title=str(row["title"])[:20],
            file_id=target.file_id,
            aigc_flag=True,
        )
    return OralWorkResult("submitted", provider_task_id=task_id)


def prepare_oral_work(conn: BusinessConnection, lease: OralWorkLease) -> OralWorkLease:
    """Load immutable provider/storage inputs before leaving the read transaction."""
    row = dict(
        conn.execute(
            {
                "avatar_submit": """
                    SELECT clone.*, asset.storage_uri AS source_storage_uri
                    FROM oral_avatars AS clone JOIN assets AS asset ON asset.id = clone.source_asset_id
                    WHERE clone.id = %s
                """,
                "voice_submit": """
                    SELECT clone.*, asset.storage_uri AS source_storage_uri
                    FROM oral_voices AS clone JOIN assets AS asset ON asset.id = clone.source_asset_id
                    WHERE clone.id = %s
                """,
                "task_submit": """
                    SELECT task.*, avatar.vendor_avatar_id, voice.vendor_voice_id,
                           asset.storage_uri AS audio_storage_uri
                    FROM oral_tasks AS task
                    JOIN oral_avatars AS avatar ON avatar.id = task.avatar_id
                    LEFT JOIN oral_voices AS voice ON voice.id = task.voice_id
                    LEFT JOIN assets AS asset ON asset.id = task.audio_asset_id
                    WHERE task.id = %s
                """,
                "avatar_poll": "SELECT * FROM oral_avatars WHERE id = %s",
                "voice_poll": "SELECT * FROM oral_voices WHERE id = %s",
                "task_poll": "SELECT * FROM oral_tasks WHERE id = %s",
                "task_archive": "SELECT * FROM oral_tasks WHERE id = %s",
            }[lease.kind],
            (lease.record_id,),
        ).fetchone()
    )
    return OralWorkLease(lease.kind, lease.record_id, lease.worker_id, row)


def finalize_oral_work(
    conn: BusinessConnection,
    *,
    lease: OralWorkLease,
    result: OralWorkResult,
) -> None:
    """CAS one worker result and finalize wallet state in the same transaction."""
    table = (
        "oral_avatars"
        if lease.kind.startswith("avatar")
        else "oral_voices"
        if lease.kind.startswith("voice")
        else "oral_tasks"
    )
    now = _now()
    retry_at = _iso(now + timedelta(seconds=15))
    with conn:
        if lease.kind.endswith("submit"):
            if result.outcome == "submitted":
                if table == "oral_tasks":
                    sql = """
                        UPDATE oral_tasks SET status = 'RUNNING', submission_state = 'SUBMITTED',
                            provider_charge_state = 'CHARGED', vendor_task_id = %s,
                            lease_owner = NULL, lease_expires_at = NULL,
                            next_attempt_at = %s, error_message = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND status = 'SUBMITTING' AND lease_owner = %s
                    """
                else:
                    sql = f"""
                        UPDATE {table} SET status = 'RUNNING', submission_state = 'SUBMITTED',
                            vendor_task_id = %s, lease_owner = NULL, lease_expires_at = NULL,
                            next_attempt_at = %s, error_message = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND submission_state = 'SUBMITTING' AND lease_owner = %s
                    """  # noqa: S608 - fixed table
                cursor = conn.execute(
                    sql,
                    (result.provider_task_id, retry_at, lease.record_id, lease.worker_id),
                )
            else:
                uncertain = result.outcome == "uncertain"
                if table == "oral_tasks":
                    status = "SUBMISSION_UNCERTAIN" if uncertain else "FAILED"
                    submission = "SUBMISSION_UNKNOWN" if uncertain else "FAILED"
                    cursor = conn.execute(
                        """
                        UPDATE oral_tasks SET status = %s, submission_state = %s,
                            provider_charge_state = %s,
                            lease_owner = NULL, lease_expires_at = NULL,
                            next_attempt_at = NULL, error_message = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND status = 'SUBMITTING' AND lease_owner = %s
                        """,
                        (
                            status,
                            submission,
                            "UNKNOWN" if uncertain else "NOT_CHARGED",
                            result.message,
                            lease.record_id,
                            lease.worker_id,
                        ),
                    )
                else:
                    submission = "SUBMISSION_UNKNOWN" if uncertain else "FAILED"
                    status = "PENDING" if uncertain else "FAILED"
                    cursor = conn.execute(
                        f"""
                        UPDATE {table} SET status = %s, submission_state = %s,
                            lease_owner = NULL, lease_expires_at = NULL,
                            next_attempt_at = NULL, error_message = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND submission_state = 'SUBMITTING' AND lease_owner = %s
                        """,  # noqa: S608 - fixed table
                        (status, submission, result.message, lease.record_id, lease.worker_id),
                    )
                if cursor.rowcount == 1 and table == "oral_tasks" and not uncertain:
                    finalize_oral_billing(conn, oral_task_id=lease.record_id)
            if cursor.rowcount != 1:
                raise OralLeaseLostError("oral submission lease was lost")
            return

        if lease.kind in {"avatar_poll", "voice_poll"}:
            if result.outcome == "waiting":
                cursor = conn.execute(
                    f"""
                    UPDATE {table} SET lease_owner = NULL, lease_expires_at = NULL,
                        next_attempt_at = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,  # noqa: S608
                    (retry_at, lease.record_id, lease.worker_id),
                )
            elif result.outcome == "failed":
                cursor = conn.execute(
                    f"""
                    UPDATE {table} SET status = 'FAILED', submission_state = 'FAILED',
                        lease_owner = NULL, lease_expires_at = NULL, next_attempt_at = NULL,
                        error_message = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,  # noqa: S608
                    (result.message, lease.record_id, lease.worker_id),
                )
            elif lease.kind == "avatar_poll":
                cursor = conn.execute(
                    """
                    UPDATE oral_avatars SET status = 'READY', vendor_avatar_id = %s,
                        lease_owner = NULL, lease_expires_at = NULL, next_attempt_at = NULL,
                        error_message = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,
                    (result.provider_resource_id, lease.record_id, lease.worker_id),
                )
            else:
                if result.stored is None:
                    raise ValueError("voice ready result requires archived demo")
                asset_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO assets (
                        id, project_id, kind, storage_uri, sha256, size_bytes,
                        content_type, created_by_user_id
                    ) VALUES (%s, NULL, 'oral_audio', %s, %s, %s, 'audio/mpeg', %s)
                    """,
                    (
                        asset_id,
                        result.stored.uri,
                        result.stored.sha256,
                        result.stored.size,
                        lease.row["owner_user_id"],
                    ),
                )
                cursor = conn.execute(
                    """
                    UPDATE oral_voices SET status = 'READY', vendor_voice_id = %s,
                        demo_asset_id = %s, lease_owner = NULL, lease_expires_at = NULL,
                        next_attempt_at = NULL, error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,
                    (
                        result.provider_resource_id,
                        asset_id,
                        lease.record_id,
                        lease.worker_id,
                    ),
                )
            if cursor.rowcount != 1:
                raise OralLeaseLostError("oral clone lease was lost")
            return

        if lease.kind == "task_poll":
            if result.outcome == "archive":
                cursor = conn.execute(
                    """
                    UPDATE oral_tasks SET status = 'ARCHIVING', provider_result_url = %s,
                        duration_sec = %s, lease_owner = NULL, lease_expires_at = NULL,
                        next_attempt_at = %s, error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,
                    (
                        result.provider_result_url,
                        result.duration_sec,
                        _iso(now),
                        lease.record_id,
                        lease.worker_id,
                    ),
                )
            elif result.outcome == "failed":
                cursor = conn.execute(
                    """
                    UPDATE oral_tasks SET status = 'FAILED', lease_owner = NULL,
                        lease_expires_at = NULL, next_attempt_at = NULL, error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,
                    (result.message, lease.record_id, lease.worker_id),
                )
                if cursor.rowcount == 1:
                    finalize_oral_billing(conn, oral_task_id=lease.record_id)
            else:
                cursor = conn.execute(
                    """
                    UPDATE oral_tasks SET lease_owner = NULL, lease_expires_at = NULL,
                        next_attempt_at = %s, error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                    """,
                    (retry_at, result.message, lease.record_id, lease.worker_id),
                )
            if cursor.rowcount != 1:
                raise OralLeaseLostError("oral poll lease was lost")
            return

        if result.outcome == "ready" and result.stored is not None:
            asset_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO assets (
                    id, project_id, kind, storage_uri, sha256, size_bytes,
                    content_type, created_by_user_id
                ) VALUES (%s, NULL, 'oral_video', %s, %s, %s, 'video/mp4', %s)
                """,
                (
                    asset_id,
                    result.stored.uri,
                    result.stored.sha256,
                    result.stored.size,
                    lease.row["owner_user_id"],
                ),
            )
            cursor = conn.execute(
                """
                UPDATE oral_tasks SET status = 'SUCCEEDED', result_asset_id = %s,
                    lease_owner = NULL, lease_expires_at = NULL, next_attempt_at = NULL,
                    error_message = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'ARCHIVING' AND lease_owner = %s
                """,
                (asset_id, lease.record_id, lease.worker_id),
            )
            if cursor.rowcount == 1:
                finalize_oral_billing(conn, oral_task_id=lease.record_id)
        else:
            cursor = conn.execute(
                """
                UPDATE oral_tasks SET status = 'ARCHIVE_FAILED', lease_owner = NULL,
                    lease_expires_at = NULL, next_attempt_at = NULL, error_message = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'ARCHIVING' AND lease_owner = %s
                """,
                (result.message, lease.record_id, lease.worker_id),
            )
        if cursor.rowcount != 1:
            raise OralLeaseLostError("oral archive lease was lost")


def request_oral_archive_retry(
    conn: BusinessConnection,
    *,
    task_id: str,
    owner_user_id: str,
) -> dict[str, Any]:
    with conn:
        cursor = conn.execute(
            """
            UPDATE oral_tasks SET status = 'ARCHIVING', next_attempt_at = %s,
                error_message = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND owner_user_id = %s AND status = 'ARCHIVE_FAILED'
              AND provider_result_url IS NOT NULL
            """,
            (_iso(_now()), task_id, owner_user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("only an archive-failed oral task with a result URL can retry")
    row = conn.execute(
        "SELECT * FROM oral_tasks WHERE id = %s AND owner_user_id = %s",
        (task_id, owner_user_id),
    ).fetchone()
    return dict(row)
