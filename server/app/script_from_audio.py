"""工作台"提取文案"链路：上传视频 → 抽音轨 → ASR 转写（异步任务）。

任务编排与 ``script_rewrite`` 同款（PENDING→RUNNING→终态 + 租约恢复 +
SUBMISSION_UNCERTAIN）。管线：存储取原视频字节 → 本机 ffmpeg 抽小音轨 →
临时对象上传存储并拿签名 URL → ASR 转写 → **临时音频即删**（成功与失败
终态都删除，重试时重新抽取）。转写全文放在任务 result_json——原始上传
没有镜头卡版本，无法写生成门禁管制的 ``/projects/{id}/scripts``，文案
工坊从任务结果取文本回填草稿，终稿发布仍走唯一的显式脚本版本路径。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.asr import (
    AsrProvider,
    AsrProviderError,
    TranscriptResult,
    get_asr_provider,
)
from app.db_portable import BusinessConnection
from app.media_tools import (
    MediaToolFailed,
    MediaToolUnavailable,
    extract_audio,
    probe_duration_seconds,
    resolve_media_binary,
)
from app.permissions import require_not_auditor, require_project_access
from app.storage import StorageAdapter

logger = logging.getLogger("app.script_from_audio")

SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES = 20
SCRIPT_FROM_AUDIO_RECOVERY_BACKOFF_SECONDS = 30
SCRIPT_FROM_AUDIO_MAX_SOURCE_BYTES = 2_000_000_000
_DOWNLOAD_INTENT_EXPIRES = timedelta(minutes=30)


class ScriptFromAudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_asset_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ScriptFromAudioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    duration_sec: float | None = None
    language: str | None = None


class ScriptFromAudioTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    status: str
    attempt: int
    result: ScriptFromAudioResult | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


def script_from_audio_task_response(row: sqlite3.Row) -> ScriptFromAudioTaskResponse:
    result_json = row["result_json"]
    result: ScriptFromAudioResult | None = None
    if result_json is not None:
        payload = json.loads(str(result_json))
        result = ScriptFromAudioResult(
            text=str(payload.get("text", "")),
            duration_sec=(
                None if payload.get("duration_sec") is None else float(payload["duration_sec"])
            ),
            language=(None if payload.get("language") is None else str(payload["language"])),
        )
    return ScriptFromAudioTaskResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        status=str(row["status"]),
        attempt=int(row["attempt"]),
        result=result,
        error_code=None if row["error_code"] is None else str(row["error_code"]),
        error_message=(
            None if row["error_message_redacted"] is None else str(row["error_message_redacted"])
        ),
        retryable=bool(row["retryable"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=None if row["started_at"] is None else str(row["started_at"]),
        completed_at=(None if row["completed_at"] is None else str(row["completed_at"])),
    )


@dataclass(frozen=True)
class ScriptFromAudioTaskLease:
    id: str
    project_id: str
    created_by_user_id: str
    worker_id: str
    lease_token: str
    attempt: int
    provider_task_id: str | None = None


class ProviderTaskCheckpointResult(StrEnum):
    CURRENT_LEASE = "CURRENT_LEASE"
    LATE_UNCERTAIN = "LATE_UNCERTAIN"


@dataclass
class PreparedScriptFromAudio:
    task_id: str
    project_id: str
    asset_id: str
    object_key: str
    storage: StorageAdapter
    asr: AsrProvider
    ffmpeg_path: str
    ffprobe_path: str | None
    provider_task_id: str | None = None


@dataclass(frozen=True)
class PreparedScriptFromAudioSubmission:
    storage: StorageAdapter
    asr: AsrProvider
    temporary_object_key: str | None
    audio_url: str | None
    duration_sec: float | None
    provider_task_id: str | None = None


def script_from_audio_error(status_code: int, code: str, message: str) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def enqueue_script_from_audio_task(
    conn: BusinessConnection,
    *,
    actor: object,
    project_id: str,
    source_asset_id: str,
    idempotency_key: str,
) -> sqlite3.Row:
    require_not_auditor(
        conn,
        actor=actor,  # type: ignore[arg-type]
        action="project.script_from_audio",
        entity_type="project",
        entity_id=project_id,
    )
    require_project_access(
        conn,
        actor=actor,  # type: ignore[arg-type]
        project_id=project_id,
        action="project.script_from_audio",
    )
    # Fail fast before a task is accepted; the worker re-resolves the
    # provider later and never persists credentials in request_json.
    get_asr_provider(conn)
    asset = conn.execute(
        "SELECT id FROM assets WHERE id = %s AND project_id = %s",
        (source_asset_id, project_id),
    ).fetchone()
    if asset is None:
        raise script_from_audio_error(
            404,
            "SCRIPT_FROM_AUDIO_SOURCE_ASSET_MISSING",
            "来源视频不存在或已删除，请重新上传。",
        )
    request_payload = {"source_asset_id": source_asset_id}
    request_hash = hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    replay = conn.execute(
        """
        SELECT * FROM script_from_audio_tasks
        WHERE project_id = %s AND idempotency_key = %s
        """,
        (project_id, idempotency_key),
    ).fetchone()
    if replay is not None:
        if str(replay["request_hash"]) != request_hash:
            raise script_from_audio_error(
                409,
                "SCRIPT_FROM_AUDIO_IDEMPOTENCY_CONFLICT",
                "提取内容已经变化，请重新提交。",
            )
        return cast(sqlite3.Row, replay)
    active = conn.execute(
        """
        SELECT * FROM script_from_audio_tasks
        WHERE project_id = %s AND status IN ('PENDING','RUNNING','SUBMISSION_UNCERTAIN')
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if active is not None:
        if str(active["request_hash"]) != request_hash:
            raise script_from_audio_error(
                409,
                "SCRIPT_FROM_AUDIO_ALREADY_RUNNING",
                "该项目已有文案提取任务在进行，请等待完成。",
            )
        return cast(sqlite3.Row, active)

    task_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO script_from_audio_tasks (
            id, project_id, source_asset_id, created_by_user_id,
            idempotency_key, request_hash, request_json, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
        ON CONFLICT DO NOTHING
        """,
        (
            task_id,
            project_id,
            source_asset_id,
            actor.id,  # type: ignore[attr-defined]
            idempotency_key,
            request_hash,
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    row = conn.execute(
        "SELECT * FROM script_from_audio_tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT * FROM script_from_audio_tasks
            WHERE project_id = %s AND status IN ('PENDING','RUNNING','SUBMISSION_UNCERTAIN')
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        raise script_from_audio_error(
            409,
            "SCRIPT_FROM_AUDIO_ENQUEUE_CONFLICT",
            "提取任务状态已经变化，请重试。",
        )
    from app.permissions import write_audit

    write_audit(
        conn,
        actor=actor,  # type: ignore[arg-type]
        action="project.script_from_audio_enqueued",
        entity_type="script_from_audio_task",
        entity_id=str(row["id"]),
        metadata={"project_id": project_id, "request_hash": request_hash},
    )
    return cast(sqlite3.Row, row)


def acquire_script_from_audio_task(
    conn: BusinessConnection,
    *,
    worker_id: str,
) -> ScriptFromAudioTaskLease | None:
    lease_seconds = SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES * 60
    if conn.is_postgres:
        conn.execute(
            """
        UPDATE script_from_audio_tasks
        SET status = 'PENDING', locked_by = NULL, lease_token = NULL, locked_until = NULL,
            error_code = NULL, error_message_redacted = NULL, retryable = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'RUNNING' AND provider_started_at IS NULL
          AND locked_until IS NOT NULL
          AND locked_until::timestamptz <= CURRENT_TIMESTAMP
            """
        )
        conn.execute(
            """
        UPDATE script_from_audio_tasks
        SET status = 'SUBMISSION_UNCERTAIN', locked_by = NULL, lease_token = NULL,
            locked_until = NULL,
            error_code = 'SCRIPT_FROM_AUDIO_SUBMISSION_UNCERTAIN',
            error_message_redacted = %s, retryable = 0,
            completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE status = 'RUNNING' AND provider_started_at IS NOT NULL
          AND locked_until IS NOT NULL
          AND locked_until::timestamptz <= CURRENT_TIMESTAMP
            """,
            ("语音转写请求可能已经送达服务商，请人工确认后再决定是否重试。",),
        )
    else:
        conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET status = 'PENDING', locked_by = NULL, lease_token = NULL, locked_until = NULL,
                error_code = NULL, error_message_redacted = NULL, retryable = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'RUNNING' AND provider_started_at IS NULL
              AND locked_until IS NOT NULL AND datetime(locked_until) <= CURRENT_TIMESTAMP
            """
        )
        conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET status = 'SUBMISSION_UNCERTAIN', locked_by = NULL, lease_token = NULL,
                locked_until = NULL,
                error_code = 'SCRIPT_FROM_AUDIO_SUBMISSION_UNCERTAIN',
                error_message_redacted = %s, retryable = 0,
                completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE status = 'RUNNING' AND provider_started_at IS NOT NULL
              AND locked_until IS NOT NULL AND datetime(locked_until) <= CURRENT_TIMESTAMP
            """,
            ("语音转写请求可能已经送达服务商，请人工确认后再决定是否重试。",),
        )
    lease_token = str(uuid4())
    if conn.is_postgres:
        row = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET status = 'RUNNING', locked_by = %s, lease_token = %s,
                locked_until = (CURRENT_TIMESTAMP + (%s * interval '1 second'))::text,
                completed_at = NULL, updated_at = CURRENT_TIMESTAMP,
                error_code = NULL, error_message_redacted = NULL, retryable = 0
            WHERE id = (
                SELECT id FROM script_from_audio_tasks
                WHERE status = 'SUBMISSION_UNCERTAIN' AND provider_task_id IS NOT NULL
                  AND updated_at::timestamptz <= CURRENT_TIMESTAMP
                      - (%s * interval '1 second')
                ORDER BY updated_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) AND status = 'SUBMISSION_UNCERTAIN' AND provider_task_id IS NOT NULL
            RETURNING *
            """,
            (
                worker_id,
                lease_token,
                lease_seconds,
                SCRIPT_FROM_AUDIO_RECOVERY_BACKOFF_SECONDS,
            ),
        ).fetchone()
    else:
        row = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET status = 'RUNNING', locked_by = %s, lease_token = %s,
                locked_until = datetime('now', %s),
                completed_at = NULL, updated_at = CURRENT_TIMESTAMP,
                error_code = NULL, error_message_redacted = NULL, retryable = 0
            WHERE id = (
                SELECT id FROM script_from_audio_tasks
                WHERE status = 'SUBMISSION_UNCERTAIN' AND provider_task_id IS NOT NULL
                  AND datetime(updated_at) <= datetime('now', %s)
                ORDER BY updated_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) AND status = 'SUBMISSION_UNCERTAIN' AND provider_task_id IS NOT NULL
            RETURNING *
            """,
            (
                worker_id,
                lease_token,
                f"+{SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES} minutes",
                f"-{SCRIPT_FROM_AUDIO_RECOVERY_BACKOFF_SECONDS} seconds",
            ),
        ).fetchone()
    if row is not None:
        conn.commit()
        return ScriptFromAudioTaskLease(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            created_by_user_id=str(row["created_by_user_id"]),
            worker_id=worker_id,
            lease_token=lease_token,
            attempt=int(row["attempt"]),
            provider_task_id=str(row["provider_task_id"]),
        )
    if conn.is_postgres:
        row = conn.execute(
            """
        UPDATE script_from_audio_tasks
        SET status = 'RUNNING', attempt = attempt + 1,
            locked_by = %s, lease_token = %s,
            locked_until = (CURRENT_TIMESTAMP + (%s * interval '1 second'))::text,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP::text),
            updated_at = CURRENT_TIMESTAMP,
            error_code = NULL, error_message_redacted = NULL, retryable = 0
        WHERE id = (
            SELECT id FROM script_from_audio_tasks
            WHERE status = 'PENDING'
            ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
        ) AND status = 'PENDING'
        RETURNING *
            """,
            (worker_id, lease_token, lease_seconds),
        ).fetchone()
    else:
        row = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET status = 'RUNNING', attempt = attempt + 1,
                locked_by = %s, lease_token = %s,
                locked_until = datetime('now', %s),
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP,
                error_code = NULL, error_message_redacted = NULL, retryable = 0
            WHERE id = (
                SELECT id FROM script_from_audio_tasks
                WHERE status = 'PENDING'
                ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) AND status = 'PENDING'
            RETURNING *
            """,
            (worker_id, lease_token, f"+{SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES} minutes"),
        ).fetchone()
    conn.commit()
    if row is None:
        return None
    return ScriptFromAudioTaskLease(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        created_by_user_id=str(row["created_by_user_id"]),
        worker_id=worker_id,
        lease_token=lease_token,
        attempt=int(row["attempt"]),
    )


def _require_leased_task(conn: BusinessConnection, lease: ScriptFromAudioTaskLease) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM script_from_audio_tasks WHERE id = %s AND status = 'RUNNING' "
        "AND locked_by = %s AND lease_token = %s AND attempt = %s",
        (lease.id, lease.worker_id, lease.lease_token, lease.attempt),
    ).fetchone()
    if row is None:
        raise script_from_audio_error(409, "SCRIPT_FROM_AUDIO_LEASE_LOST", "任务租约已失效。")
    return cast(sqlite3.Row, row)


def prepare_script_from_audio_task(
    conn: BusinessConnection,
    *,
    lease: ScriptFromAudioTaskLease,
    storage: StorageAdapter,
) -> PreparedScriptFromAudio:
    row = _require_leased_task(conn, lease)
    active_provider = get_asr_provider(conn)
    if lease.provider_task_id is not None:
        return PreparedScriptFromAudio(
            task_id=lease.id,
            project_id=lease.project_id,
            asset_id="",
            object_key="",
            storage=storage,
            asr=active_provider,
            ffmpeg_path="",
            ffprobe_path=None,
            provider_task_id=lease.provider_task_id,
        )
    payload = json.loads(str(row["request_json"]))
    asset_id = str(payload.get("source_asset_id", ""))
    asset = conn.execute(
        "SELECT * FROM assets WHERE id = %s AND project_id = %s",
        (asset_id, lease.project_id),
    ).fetchone()
    if asset is None:
        raise script_from_audio_error(
            404,
            "SCRIPT_FROM_AUDIO_SOURCE_ASSET_MISSING",
            "来源视频不存在或已删除，请重新上传。",
        )
    storage_uri = str(asset["storage_uri"])
    object_key = _object_key_from_uri(storage_uri)
    try:
        ffmpeg_path = resolve_media_binary("ffmpeg")
        ffprobe_path = resolve_media_binary("ffprobe")
    except MediaToolUnavailable as exc:
        raise script_from_audio_error(
            503,
            "SCRIPT_FROM_AUDIO_MEDIA_TOOL_MISSING",
            str(exc),
        ) from exc
    return PreparedScriptFromAudio(
        task_id=lease.id,
        project_id=lease.project_id,
        asset_id=asset_id,
        object_key=object_key,
        storage=storage,
        asr=active_provider,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
    )


def mark_script_from_audio_submission_started(
    conn: BusinessConnection,
    *,
    lease: ScriptFromAudioTaskLease,
) -> bool:
    if conn.is_postgres:
        updated = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET provider_started_at = CURRENT_TIMESTAMP,
                locked_until = (CURRENT_TIMESTAMP + (%s * interval '1 second'))::text,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND locked_by = %s AND lease_token = %s AND attempt = %s
              AND status = 'RUNNING'
              AND (
                (provider_started_at IS NULL AND provider_task_id IS NULL)
                OR (provider_started_at IS NOT NULL AND provider_task_id = %s)
              )
              AND locked_until::timestamptz > CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES * 60,
                lease.id,
                lease.worker_id,
                lease.lease_token,
                lease.attempt,
                lease.provider_task_id,
            ),
        ).fetchone()
    else:
        updated = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET provider_started_at = CURRENT_TIMESTAMP,
                locked_until = datetime('now', %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND locked_by = %s AND lease_token = %s AND attempt = %s
              AND status = 'RUNNING'
              AND (
                (provider_started_at IS NULL AND provider_task_id IS NULL)
                OR (provider_started_at IS NOT NULL AND provider_task_id = %s)
              )
              AND datetime(locked_until) > CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                f"+{SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES} minutes",
                lease.id,
                lease.worker_id,
                lease.lease_token,
                lease.attempt,
                lease.provider_task_id,
            ),
        ).fetchone()
    if updated is None:
        if not conn.is_postgres:
            conn.rollback()
        raise script_from_audio_error(409, "SCRIPT_FROM_AUDIO_LEASE_LOST", "任务租约已失效。")
    conn.commit()
    return True


def renew_script_from_audio_lease(
    conn: BusinessConnection,
    *,
    lease: ScriptFromAudioTaskLease,
) -> bool:
    """续租当前付费调用；过期、换 token 或换 attempt 均不得恢复。"""
    if conn.is_postgres:
        updated = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET locked_until = (CURRENT_TIMESTAMP + (%s * interval '1 second'))::text,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND locked_by = %s AND lease_token = %s AND attempt = %s
              AND status = 'RUNNING' AND provider_started_at IS NOT NULL
              AND locked_until::timestamptz > CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES * 60,
                lease.id,
                lease.worker_id,
                lease.lease_token,
                lease.attempt,
            ),
        ).fetchone()
    else:
        updated = conn.execute(
            """
            UPDATE script_from_audio_tasks
            SET locked_until = datetime('now', %s), updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND locked_by = %s AND lease_token = %s AND attempt = %s
              AND status = 'RUNNING' AND provider_started_at IS NOT NULL
              AND datetime(locked_until) > CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                f"+{SCRIPT_FROM_AUDIO_TASK_LEASE_MINUTES} minutes",
                lease.id,
                lease.worker_id,
                lease.lease_token,
                lease.attempt,
            ),
        ).fetchone()
        conn.commit()
    return updated is not None


def prepare_script_from_audio_submission(
    work: PreparedScriptFromAudio,
) -> PreparedScriptFromAudioSubmission:
    """完成可安全重试的本地与存储准备，尚未调用 ASR。"""
    if work.provider_task_id is not None:
        return PreparedScriptFromAudioSubmission(
            storage=work.storage,
            asr=work.asr,
            temporary_object_key=None,
            audio_url=None,
            duration_sec=None,
            provider_task_id=work.provider_task_id,
        )
    video_bytes = work.storage.get_object(work.object_key)
    tmp_key = f"tmp/asr/{work.project_id}/{hashlib.sha256(video_bytes).hexdigest()[:32]}.m4a"
    with tempfile.TemporaryDirectory(prefix="script-from-audio-") as tmp_dir:
        video_path = Path(tmp_dir) / "source-video"
        audio_path = Path(tmp_dir) / "extracted-audio.m4a"
        video_path.write_bytes(video_bytes)
        try:
            extract_audio(work.ffmpeg_path, video_path, audio_path)
            audio_bytes = audio_path.read_bytes()
        except MediaToolFailed as exc:
            raise AsrProviderError(f"音轨抽取失败：{exc}") from exc
        duration = (
            probe_duration_seconds(work.ffprobe_path, audio_path) if work.ffprobe_path else None
        )
        work.storage.put_object(tmp_key, audio_bytes, content_type="audio/mp4")
        try:
            intent = work.storage.create_download_intent(
                tmp_key,
                expires_in=_DOWNLOAD_INTENT_EXPIRES,
                can_read=True,
            )
        except Exception:
            try:
                work.storage.delete_object(tmp_key, actor_id="script-from-audio-worker")
            except Exception:
                logger.warning("temporary ASR audio cleanup failed for key %s", tmp_key)
            raise
    return PreparedScriptFromAudioSubmission(
        storage=work.storage,
        asr=work.asr,
        temporary_object_key=tmp_key,
        audio_url=intent.url,
        duration_sec=duration,
    )


def cleanup_script_from_audio_submission(work: PreparedScriptFromAudioSubmission) -> None:
    if work.temporary_object_key is None:
        return
    try:
        work.storage.delete_object(work.temporary_object_key, actor_id="script-from-audio-worker")
    except Exception:  # pragma: no cover - cleanup best effort
        logger.warning("temporary ASR audio cleanup failed for key %s", work.temporary_object_key)


def perform_script_from_audio_provider_call(
    work: PreparedScriptFromAudioSubmission,
    *,
    on_task_created: Callable[[str], None] | None = None,
    on_poll: Callable[[], None] | None = None,
) -> TranscriptResult:
    """ASR 是唯一可能已被上游受理的步骤；调用后无条件清理临时音频。"""
    try:
        if work.provider_task_id is not None:
            return work.asr.resume_transcription(work.provider_task_id, on_poll=on_poll)
        if work.audio_url is None:
            raise AsrProviderError("语音转写临时音频未准备完成")
        return work.asr.transcribe(
            work.audio_url,
            duration_sec=work.duration_sec,
            on_task_created=on_task_created,
            on_poll=on_poll,
        )
    finally:
        cleanup_script_from_audio_submission(work)


def perform_script_from_audio_task(work: PreparedScriptFromAudio) -> TranscriptResult:
    """SQLite 兼容入口；PG worker 使用拆分后的两阶段函数。"""
    return perform_script_from_audio_provider_call(prepare_script_from_audio_submission(work))


def record_script_from_audio_provider_task(
    conn: BusinessConnection,
    *,
    lease: ScriptFromAudioTaskLease,
    provider_task_id: str,
) -> ProviderTaskCheckpointResult:
    """Persist the upstream identity before polling so crashes remain reconcilable."""
    updated = conn.execute(
        """
        UPDATE script_from_audio_tasks
        SET provider_task_id = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND attempt = %s AND provider_task_id IS NULL
          AND provider_started_at IS NOT NULL
          AND (
            (status = 'RUNNING' AND lease_token = %s)
            OR (status = 'SUBMISSION_UNCERTAIN' AND lease_token IS NULL)
          )
        RETURNING status
        """,
        (
            provider_task_id,
            lease.id,
            lease.attempt,
            lease.lease_token,
        ),
    ).fetchone()
    if updated is None:
        raise script_from_audio_error(409, "SCRIPT_FROM_AUDIO_LEASE_LOST", "任务租约已失效。")
    conn.commit()
    if str(updated["status"]) == "SUBMISSION_UNCERTAIN":
        return ProviderTaskCheckpointResult.LATE_UNCERTAIN
    return ProviderTaskCheckpointResult.CURRENT_LEASE


def complete_script_from_audio_task(
    conn: BusinessConnection,
    *,
    lease: ScriptFromAudioTaskLease,
    result: TranscriptResult,
) -> bool:
    result_payload = {
        "text": result.text,
        "duration_sec": result.duration_sec,
        "language": result.language,
    }
    updated = conn.execute(
        """
        UPDATE script_from_audio_tasks
        SET status = 'SUCCEEDED', result_json = %s,
            error_code = NULL, error_message_redacted = NULL, retryable = 0,
            completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP, locked_by = NULL,
            lease_token = NULL, locked_until = NULL, provider_started_at = NULL
        WHERE id = %s AND lease_token = %s AND attempt = %s
          AND status = 'RUNNING' AND provider_started_at IS NOT NULL
        RETURNING id
        """,
        (
            json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
            lease.id,
            lease.lease_token,
            lease.attempt,
        ),
    ).fetchone()
    if updated is None:
        raise script_from_audio_error(409, "SCRIPT_FROM_AUDIO_LEASE_LOST", "任务租约已失效。")
    conn.commit()
    return True


def fail_script_from_audio_task(
    conn: BusinessConnection,
    *,
    lease: ScriptFromAudioTaskLease,
    cause: Exception,
    submission_started: bool,
) -> bool:
    logger.warning("script-from-audio task %s failed: %s", lease.id, type(cause).__name__)
    provider_was_started = submission_started or lease.provider_task_id is not None
    retryable = 1 if not provider_was_started else 0
    provider_task_id = (
        cause.provider_task_id if isinstance(cause, AsrProviderError) else None
    ) or lease.provider_task_id
    if provider_was_started and (
        not isinstance(cause, AsrProviderError) or cause.submission_uncertain
    ):
        status = "SUBMISSION_UNCERTAIN"
        code = "SCRIPT_FROM_AUDIO_SUBMISSION_UNCERTAIN"
    elif provider_was_started:
        status = "FAILED"
        code = "SCRIPT_FROM_AUDIO_PROVIDER_FAILED"
    else:
        status = "FAILED"
        code = "SCRIPT_FROM_AUDIO_PIPELINE_FAILED"
    provider_condition = "IS NOT NULL" if provider_was_started else "IS NULL"
    updated = conn.execute(
        f"""
        UPDATE script_from_audio_tasks
        SET status = %s, error_code = %s,
            error_message_redacted = %s, retryable = %s,
            provider_task_id = COALESCE(%s, provider_task_id),
            completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP, locked_by = NULL,
            lease_token = NULL, locked_until = NULL
        WHERE id = %s AND lease_token = %s AND attempt = %s
          AND status = 'RUNNING' AND provider_started_at {provider_condition}
        RETURNING id
        """,
        (
            status,
            code,
            _redacted_message(cause),
            retryable,
            provider_task_id,
            lease.id,
            lease.lease_token,
            lease.attempt,
        ),
    ).fetchone()
    if updated is None:
        logger.warning(
            "script-from-audio stale lease could not write failure for task %s", lease.id
        )
        if not conn.is_postgres:
            conn.rollback()
        return False
    conn.commit()
    return True


def load_script_from_audio_task(conn: BusinessConnection, task_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM script_from_audio_tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    if row is None:
        raise script_from_audio_error(404, "SCRIPT_FROM_AUDIO_TASK_NOT_FOUND", "提取任务不存在。")
    return cast(sqlite3.Row, row)


def latest_script_from_audio_task(
    conn: BusinessConnection, *, project_id: str
) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT * FROM script_from_audio_tasks
        WHERE project_id = %s
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    return None if row is None else cast(sqlite3.Row, row)


def _redacted_message(cause: Exception) -> str:
    if isinstance(cause, AsrProviderError):
        return str(cause)
    from fastapi import HTTPException

    if isinstance(cause, HTTPException):
        detail = cause.detail
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
    return "文案提取管线执行失败，请稍后重试。"


def _object_key_from_uri(storage_uri: str) -> str:
    """``provider://bucket/key`` → ``key``（key 内段保留原样）。"""
    marker = "://"
    if marker not in storage_uri:
        return storage_uri
    after_scheme = storage_uri.split(marker, 1)[1]
    if "/" not in after_scheme:
        return storage_uri
    return after_scheme.split("/", 1)[1]
