"""Oral digital-human domain services (C1 / 未接通能力拆解).

Vendor-neutral by contract: no table, row, or customer-visible message may
name the upstream provider (see the red-line test in tests/test_hifly_client.py).
Polling is pull-based (no public webhook). Generation tasks reserve one wallet
credit before queueing; the worker settles success, releases terminal failure,
and retains ambiguous submissions for reconciliation without retrying them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.auth import CurrentUser
from app.character_identity import require_current_authorization
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyError, HiflySettingsUnavailable, hifly_client_from_settings
from app.media_routes import get_media_storage, storage_for_asset
from app.permissions import require_asset_access
from app.settings import SettingsRepository
from app.storage import StorageAdapter

logger = logging.getLogger(__name__)

ORAL_UNIT_PRICE_FEN_DEFAULT = 1000
MAX_ORAL_SCRIPT_CHARS = 10_000
ORAL_TASK_LEASE_SECONDS = 120
ORAL_POLL_SECONDS = 15

AvatarStatus = str  # PENDING/RUNNING/READY/FAILED
TaskStatus = str  # QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED


class OralDomainError(Exception):
    """Customer-safe oral-domain failure (message is UI-renderable)."""


def oral_unit_price_fen(conn: BusinessConnection) -> int:
    """Per-task list price for oral renders; admin-configurable via billing."""
    try:
        billing = SettingsRepository(conn).read_billing_settings()
    except Exception as exc:  # noqa: BLE001 - fail closed before reserving credits
        raise OralDomainError("口播计费配置暂不可用，请稍后重试") from exc
    try:
        price = int(billing.get("oral_unit_price_fen", ORAL_UNIT_PRICE_FEN_DEFAULT))
    except (TypeError, ValueError) as exc:
        raise OralDomainError("口播计费配置无效，请联系管理员") from exc
    if price <= 0:
        raise OralDomainError("口播计费配置无效，请联系管理员")
    return price


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _identity(conn: BusinessConnection, identity_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, owner_user_id, display_name, status, authorization_status,
                  authorization_asset_id, authorization_expires_at, source_quality_status
           FROM person_identities WHERE id = %s""",
        (identity_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _asset(conn: BusinessConnection, asset_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, kind, storage_uri, content_type FROM assets WHERE id = %s",
        (asset_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _require_own_identity(
    conn: BusinessConnection, actor: CurrentUser, identity_id: str
) -> dict[str, Any]:
    if actor.role == "auditor":
        raise OralDomainError("审计角色只能查看口播记录")
    identity = _identity(conn, identity_id)
    if identity is None or identity["owner_user_id"] != actor.id:
        raise OralDomainError("人物不存在或无权使用")
    try:
        require_current_authorization(identity)  # type: ignore[arg-type]
    except Exception as exc:
        raise OralDomainError("人物肖像授权已失效，请先更新授权") from exc
    return identity


def _require_source_asset(
    conn: BusinessConnection, *, actor: CurrentUser, asset_id: str, message: str
) -> dict[str, Any]:
    try:
        return dict(
            require_asset_access(
                conn,
                actor=actor,
                asset_id=asset_id,
                action="oral.source.read",
            )
        )
    except Exception as exc:
        raise OralDomainError(message) from exc


# ---------------------------------------------------------------------------
# Avatar / voice cloning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CloneStartResult:
    task_id: str
    status: str


def start_avatar_clone(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    identity_id: str,
    title: str,
    source_asset_id: str,
    source_kind: str,
    vendor: HiflyClient,
) -> CloneStartResult:
    if source_kind not in {"VIDEO", "IMAGE"}:
        raise OralDomainError("分身素材类型不支持")
    _require_own_identity(conn, actor, identity_id)
    asset = _require_source_asset(
        conn, actor=actor, asset_id=source_asset_id, message="素材不存在或无权使用"
    )
    clean_title = title.strip() or "口播分身"

    try:
        content = _read_asset_bytes(conn, asset)
        extension = _extension_for(asset, source_kind)
        target = vendor.create_upload_url(extension)
        vendor.upload_file(target, content)
        vendor_task_id = vendor.create_avatar_by_video(
            title=clean_title[:20], file_id=target.file_id, aigc_flag=True
        )
    except HiflyError as exc:
        raise OralDomainError(str(exc)) from exc

    avatar_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO oral_avatars (
            id, identity_id, owner_user_id, title, vendor_task_id,
            status, source_kind, source_asset_id
        ) VALUES (%s, %s, %s, %s, %s, 'RUNNING', %s, %s)
        """,
        (
            avatar_id,
            identity_id,
            actor.id,
            clean_title,
            vendor_task_id,
            source_kind,
            source_asset_id,
        ),
    )
    return CloneStartResult(task_id=avatar_id, status="RUNNING")


def start_voice_clone(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    identity_id: str,
    title: str,
    source_asset_id: str,
    vendor: HiflyClient,
) -> CloneStartResult:
    _require_own_identity(conn, actor, identity_id)
    asset = _require_source_asset(
        conn, actor=actor, asset_id=source_asset_id, message="音频素材不存在或无权使用"
    )
    clean_title = title.strip() or "克隆声音"

    try:
        content = _read_asset_bytes(conn, asset)
        target = vendor.create_upload_url("mp3")
        vendor.upload_file(target, content)
        vendor_task_id = vendor.create_voice(title=clean_title[:20], file_id=target.file_id)
    except HiflyError as exc:
        raise OralDomainError(str(exc)) from exc

    voice_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO oral_voices (
            id, identity_id, owner_user_id, title, vendor_task_id,
            status, source_asset_id
        ) VALUES (%s, %s, %s, %s, %s, 'RUNNING', %s)
        """,
        (voice_id, identity_id, actor.id, clean_title, vendor_task_id, source_asset_id),
    )
    return CloneStartResult(task_id=voice_id, status="RUNNING")


def _read_asset_bytes(conn: BusinessConnection, asset: dict[str, Any]) -> bytes:
    storage = storage_for_asset(conn, str(asset["storage_uri"]))
    key = (
        str(asset["storage_uri"]).split("/", 3)[-1]
        if "://" in str(asset["storage_uri"])
        else str(asset["storage_uri"])
    )
    try:
        return storage.get_object(key)
    except Exception as exc:  # noqa: BLE001 - surfaced as a customer-safe message
        logger.warning("oral source asset read failed: %s", type(exc).__name__)
        raise OralDomainError("素材读取失败，请重新上传") from exc


def _extension_for(asset: dict[str, Any], source_kind: str) -> str:
    content_type = str(asset.get("content_type") or "")
    if source_kind == "IMAGE" or content_type.startswith("image/"):
        return "png"
    if content_type.endswith("webm"):
        return "webm"
    return "mp4"


# ---------------------------------------------------------------------------
# Oral task lifecycle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OralTaskCreated:
    task_id: str
    status: str
    estimated_cost_fen: int
    replayed: bool


def create_oral_task(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    identity_id: str,
    avatar_id: str,
    voice_id: str | None,
    mode: str,
    title: str,
    script_text: str | None,
    audio_asset_id: str | None,
    subtitle: dict[str, Any] | None,
    idempotency_key: str,
    vendor: HiflyClient | None = None,
) -> OralTaskCreated:
    if mode not in {"TTS", "AUDIO"}:
        raise OralDomainError("口播模式不支持")
    if not title.strip():
        raise OralDomainError("请填写作品标题")
    _require_own_identity(conn, actor, identity_id)

    avatar = conn.execute(
        "SELECT id, status, identity_id FROM oral_avatars WHERE id = %s AND owner_user_id = %s",
        (avatar_id, actor.id),
    ).fetchone()
    if avatar is None or str(avatar["status"]) != "READY":
        raise OralDomainError("请选择已就绪的口播分身")
    if avatar["identity_id"] != identity_id:
        raise OralDomainError("口播分身与人物不匹配")

    effective_voice = voice_id
    if mode == "TTS":
        if not script_text or not script_text.strip():
            raise OralDomainError("请填写口播文案")
        if len(script_text) > MAX_ORAL_SCRIPT_CHARS:
            raise OralDomainError("口播文案过长（上限 1 万字）")
        if not effective_voice:
            raise OralDomainError("请选择已就绪的声音")
        voice = conn.execute(
            "SELECT id, status, identity_id FROM oral_voices WHERE id = %s AND owner_user_id = %s",
            (effective_voice, actor.id),
        ).fetchone()
        if voice is None or str(voice["status"]) != "READY":
            raise OralDomainError("请选择已就绪的声音")
        if voice["identity_id"] != identity_id:
            raise OralDomainError("声音与人物不匹配")
    else:
        effective_voice = None
        if not audio_asset_id:
            raise OralDomainError("请上传完整的口播音频")
        _require_source_asset(
            conn,
            actor=actor,
            asset_id=audio_asset_id,
            message="口播音频不存在或无权使用",
        )

    existing = conn.execute(
        "SELECT id, status, estimated_cost_fen FROM oral_tasks WHERE idempotency_key = %s",
        (idempotency_key,),
    ).fetchone()
    if existing is not None:
        return OralTaskCreated(
            task_id=str(existing["id"]),
            status=str(existing["status"]),
            estimated_cost_fen=int(existing["estimated_cost_fen"]),
            replayed=True,
        )

    project = conn.execute(
        "SELECT id FROM projects WHERE owner_user_id = %s AND status = 'ACTIVE' "
        "ORDER BY updated_at DESC, id LIMIT 1",
        (actor.id,),
    ).fetchone()
    if project is None:
        raise OralDomainError("请先创建可用项目")

    price = oral_unit_price_fen(conn)
    task_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO oral_tasks (
            id, owner_user_id, project_id, identity_id, avatar_id, voice_id, mode, title,
            script_text, audio_asset_id, subtitle_json, status,
            estimated_cost_fen, idempotency_key
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'QUEUED', %s, %s)
        """,
        (
            task_id,
            actor.id,
            str(project["id"]),
            identity_id,
            avatar_id,
            effective_voice,
            mode,
            title.strip()[:120],
            script_text,
            audio_asset_id,
            json.dumps(subtitle, ensure_ascii=False) if subtitle else None,
            price,
            idempotency_key,
        ),
    )
    _reserve_oral_billing(conn, user_id=actor.id, task_id=task_id)
    _ensure_oral_queue_cursor(conn, user_id=actor.id)
    row = _oral_task_row(conn, task_id)
    return OralTaskCreated(
        task_id=task_id,
        status=str(row["status"]),
        estimated_cost_fen=price,
        replayed=False,
    )


def _submit_oral_task(
    conn: BusinessConnection,
    *,
    task_id: str,
    vendor: HiflyClient,
) -> None:
    row = _oral_task_row(conn, task_id)
    try:
        audio_target = None
        if row["mode"] == "AUDIO":
            asset = _asset(conn, str(row["audio_asset_id"]))
            if asset is None:
                raise OralDomainError("口播音频已失效，请重新上传")
            content = _read_asset_bytes(conn, asset)
            audio_target = vendor.create_upload_url("mp3")
            vendor.upload_file(audio_target, content)
        subtitle = json.loads(str(row["subtitle_json"])) if row["subtitle_json"] else None
        if row["mode"] == "TTS":
            vendor_task_id = vendor.create_video_by_tts(
                voice=_vendor_voice_id(conn, str(row["voice_id"])),
                text=str(row["script_text"]),
                avatar=_vendor_avatar_id(conn, str(row["avatar_id"])),
                title=str(row["title"])[:20],
                aigc_flag=True,
                subtitle=subtitle,
            )
        else:
            vendor_task_id = vendor.create_video_by_audio(
                avatar=_vendor_avatar_id(conn, str(row["avatar_id"])),
                title=str(row["title"])[:20],
                file_id=audio_target.file_id if audio_target else None,
                aigc_flag=True,
            )
    except OralDomainError as exc:
        conn.execute(
            """
            UPDATE oral_tasks
            SET status = 'FAILED', error_message = %s, completed_at = CURRENT_TIMESTAMP,
                locked_by = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            (str(exc)[:500], task_id),
        )
        _finalize_oral_billing(conn, task_id=task_id, outcome="release")
        _release_oral_queue_slot(conn, task_id=task_id)
        return
    except HiflyError as exc:
        # A transport timeout may happen after the provider accepted the task.
        # Keep the reservation and require reconciliation instead of retrying
        # blindly and charging twice.
        status = "FAILED" if exc.vendor_code is not None else "SUBMISSION_UNCERTAIN"
        conn.execute(
            """
            UPDATE oral_tasks
            SET status = %s, error_message = %s,
                completed_at = CASE WHEN %s = 'FAILED' THEN CURRENT_TIMESTAMP ELSE NULL END,
                locked_by = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, str(exc)[:500], status, task_id),
        )
        if status == "FAILED":
            _finalize_oral_billing(conn, task_id=task_id, outcome="release")
        _release_oral_queue_slot(conn, task_id=task_id)
        return
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'RUNNING', vendor_task_id = %s,
            next_poll_at = now() + interval '15 seconds',
            locked_by = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (vendor_task_id, task_id),
    )


def _vendor_avatar_id(conn: BusinessConnection, avatar_id: str) -> str:
    row = conn.execute(
        "SELECT vendor_avatar_id FROM oral_avatars WHERE id = %s", (avatar_id,)
    ).fetchone()
    if row is None or not row["vendor_avatar_id"]:
        raise OralDomainError("口播分身尚未就绪")
    return str(row["vendor_avatar_id"])


def _vendor_voice_id(conn: BusinessConnection, voice_id: str) -> str:
    row = conn.execute(
        "SELECT vendor_voice_id FROM oral_voices WHERE id = %s", (voice_id,)
    ).fetchone()
    if row is None or not row["vendor_voice_id"]:
        raise OralDomainError("声音尚未就绪")
    return str(row["vendor_voice_id"])


def _oral_task_row(conn: BusinessConnection, task_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM oral_tasks WHERE id = %s", (task_id,)).fetchone()
    if row is None:
        raise OralDomainError("口播任务不存在")
    return dict(row)


def _ensure_oral_queue_cursor(conn: BusinessConnection, *, user_id: str) -> None:
    if not conn.is_postgres:
        return
    conn.execute(
        "INSERT INTO user_queue_cursors (user_id, last_dispatched_at, running_tasks_count) "
        "VALUES (%s, now(), 0) ON CONFLICT (user_id) DO NOTHING",
        (user_id,),
    )


def _release_oral_queue_slot(conn: BusinessConnection, *, task_id: str) -> None:
    if not conn.is_postgres:
        return
    conn.execute(
        """
        UPDATE user_queue_cursors SET
            running_tasks_count = GREATEST(running_tasks_count - 1, 0),
            last_dispatched_at = now()
        WHERE user_id = (SELECT owner_user_id FROM oral_tasks WHERE id = %s)
        """,
        (task_id,),
    )


def acquire_oral_task(conn: BusinessConnection, *, worker_id: str) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    locked_until = (now + timedelta(seconds=ORAL_TASK_LEASE_SECONDS)).isoformat()
    if conn.is_postgres:
        expired = conn.execute(
            """
            UPDATE oral_tasks SET status = 'SUBMISSION_UNCERTAIN', locked_by = NULL,
                locked_until = NULL, error_message = '提交结果未知，等待人工对账',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'SUBMITTING' AND locked_until::timestamptz <= now()
            RETURNING id
            """
        ).fetchall()
        for row in expired:
            _release_oral_queue_slot(conn, task_id=str(row["id"]))
        continuation = conn.execute(
            """
            UPDATE oral_tasks SET locked_by = %s, locked_until = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM oral_tasks
                WHERE status = 'RUNNING'
                  AND (locked_until IS NULL OR locked_until::timestamptz <= now())
                  AND (next_poll_at IS NULL OR next_poll_at::timestamptz <= now())
                ORDER BY next_poll_at, created_at, id
                LIMIT 1 FOR UPDATE SKIP LOCKED
            ) RETURNING *
            """,
            (worker_id, locked_until),
        ).fetchone()
        if continuation is not None:
            return dict(continuation)
        cursor = conn.execute(
            """
            SELECT user_id FROM user_queue_cursors
            WHERE running_tasks_count = 0
              AND EXISTS (
                  SELECT 1 FROM oral_tasks
                  WHERE owner_user_id = user_queue_cursors.user_id AND status = 'QUEUED'
              )
            ORDER BY last_dispatched_at, user_id
            LIMIT 1 FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if cursor is None:
            return None
        user_id = str(cursor["user_id"])
        row = conn.execute(
            """
            UPDATE oral_tasks SET status = 'SUBMITTING', attempt = attempt + 1,
                submitted_at = COALESCE(submitted_at::timestamptz, CURRENT_TIMESTAMP),
                locked_by = %s, locked_until = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM oral_tasks WHERE owner_user_id = %s AND status = 'QUEUED'
                ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) RETURNING *
            """,
            (worker_id, locked_until, user_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE user_queue_cursors SET running_tasks_count = running_tasks_count + 1, "
            "last_dispatched_at = now() WHERE user_id = %s",
            (user_id,),
        )
        return dict(row)
    row = conn.execute(
        """
        UPDATE oral_tasks SET
            status = CASE WHEN status = 'QUEUED' THEN 'SUBMITTING' ELSE status END,
            attempt = attempt + CASE WHEN status = 'QUEUED' THEN 1 ELSE 0 END,
            locked_by = %s, locked_until = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM oral_tasks
            WHERE status = 'QUEUED'
               OR (
                   status = 'RUNNING'
                   AND (next_poll_at IS NULL OR next_poll_at <= CURRENT_TIMESTAMP)
               )
            ORDER BY created_at, id LIMIT 1
        ) RETURNING *
        """,
        (worker_id, locked_until),
    ).fetchone()
    conn.commit()
    return dict(row) if row is not None else None


def run_next_oral_task(
    conn: BusinessConnection,
    *,
    worker_id: str,
    vendor: HiflyClient | None = None,
) -> str | None:
    lease = acquire_oral_task(conn, worker_id=worker_id)
    if lease is None:
        return None
    task_id = str(lease["id"])
    try:
        active_vendor = vendor or hifly_client_from_settings(conn)
    except HiflySettingsUnavailable as exc:
        conn.execute(
            "UPDATE oral_tasks SET status = 'FAILED', error_message = %s, "
            "completed_at = CURRENT_TIMESTAMP, locked_by = NULL, locked_until = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (str(exc)[:500], task_id),
        )
        _finalize_oral_billing(conn, task_id=task_id, outcome="release")
        _release_oral_queue_slot(conn, task_id=task_id)
        conn.commit()
        return task_id
    actor = CurrentUser(
        id=str(lease["owner_user_id"]),
        username=str(lease["owner_user_id"]),
        display_name=str(lease["owner_user_id"]),
        role="customer",
    )
    if str(lease["status"]) == "SUBMITTING":
        _submit_oral_task(conn, task_id=task_id, vendor=active_vendor)
    else:
        refresh_oral_task(conn, task_id=task_id, actor=actor, vendor=active_vendor)
    conn.commit()
    return task_id


def _reserve_oral_billing(conn: BusinessConnection, *, user_id: str, task_id: str) -> None:
    existing = conn.execute(
        "SELECT user_id FROM wallet_transactions "
        "WHERE oral_task_id = %s AND billing_round = 1 AND type = 'RESERVE'",
        (task_id,),
    ).fetchone()
    if existing is not None:
        if str(existing["user_id"]) != user_id:
            raise OralDomainError("口播任务账本归属异常")
        return
    updated = conn.execute(
        """
        UPDATE wallets SET available_credits = available_credits - 1,
            reserved_credits = reserved_credits + 1, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND available_credits >= 1
        """,
        (user_id,),
    )
    if updated.rowcount != 1:
        raise OralDomainError("可用次数不足，请先充值")
    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta, oral_task_id,
            billing_round, idempotency_key
        ) VALUES (%s, %s, 'RESERVE', -1, 1, %s, 1, %s)
        """,
        (str(uuid4()), user_id, task_id, f"oral:reserve:{task_id}:1"),
    )


def _finalize_oral_billing(conn: BusinessConnection, *, task_id: str, outcome: str) -> None:
    reservation = conn.execute(
        "SELECT user_id FROM wallet_transactions "
        "WHERE oral_task_id = %s AND billing_round = 1 AND type = 'RESERVE'",
        (task_id,),
    ).fetchone()
    if reservation is None:
        raise OralDomainError("口播任务缺少预扣记录")
    existing = conn.execute(
        "SELECT type FROM wallet_transactions WHERE oral_task_id = %s "
        "AND billing_round = 1 AND type IN ('SETTLE', 'RELEASE')",
        (task_id,),
    ).fetchone()
    if existing is not None:
        return
    transaction_type = "SETTLE" if outcome == "settle" else "RELEASE"
    available_delta = 0 if transaction_type == "SETTLE" else 1
    user_id = str(reservation["user_id"])
    updated = conn.execute(
        """
        UPDATE wallets SET available_credits = available_credits + %s,
            reserved_credits = reserved_credits - 1, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND reserved_credits >= 1
        """,
        (available_delta, user_id),
    )
    if updated.rowcount != 1:
        raise OralDomainError("口播任务预扣余额异常")
    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta, oral_task_id,
            billing_round, idempotency_key
        ) VALUES (%s, %s, %s, %s, -1, %s, 1, %s)
        """,
        (
            str(uuid4()),
            user_id,
            transaction_type,
            available_delta,
            task_id,
            f"oral:{transaction_type.lower()}:{task_id}:1",
        ),
    )


# ---------------------------------------------------------------------------
# Pull-based vendor refresh (no public webhook available)
# ---------------------------------------------------------------------------


def refresh_oral_task(
    conn: BusinessConnection,
    *,
    task_id: str,
    actor: CurrentUser,
    vendor: HiflyClient,
) -> dict[str, Any]:
    row = _oral_task_row(conn, task_id)
    if row["owner_user_id"] != actor.id:
        raise OralDomainError("口播任务不存在")
    if row["status"] == "RUNNING" and row["vendor_task_id"]:
        try:
            snapshot = vendor.video_task(str(row["vendor_task_id"]))
        except HiflyError as exc:
            logger.warning("oral vendor poll failed: %s", type(exc).__name__)
            return row
        if snapshot.status == "DONE":
            _archive_oral_result(
                conn,
                row=row,
                video_url=snapshot.video_url,
                duration_sec=snapshot.duration,
                vendor=vendor,
            )
        elif snapshot.status == "FAILED":
            conn.execute(
                """
            UPDATE oral_tasks
            SET status = 'FAILED', error_message = %s, completed_at = CURRENT_TIMESTAMP,
                locked_by = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
                ("数字人服务生成失败，请调整内容后重试", task_id),
            )
            _finalize_oral_billing(conn, task_id=task_id, outcome="release")
            _release_oral_queue_slot(conn, task_id=task_id)
        else:
            conn.execute(
                "UPDATE oral_tasks SET next_poll_at = now() + interval '15 seconds', "
                "locked_by = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                (task_id,),
            )
    return _oral_task_row(conn, task_id)


def _archive_oral_result(
    conn: BusinessConnection,
    *,
    row: dict[str, Any],
    video_url: str | None,
    duration_sec: int | None,
    vendor: HiflyClient,
) -> None:
    if not video_url:
        conn.execute(
            """
            UPDATE oral_tasks
            SET status = 'FAILED', error_message = %s, completed_at = CURRENT_TIMESTAMP,
                locked_by = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            ("数字人服务未返回成片地址", str(row["id"])),
        )
        _finalize_oral_billing(conn, task_id=str(row["id"]), outcome="release")
        _release_oral_queue_slot(conn, task_id=str(row["id"]))
        return
    try:
        content = vendor.download(video_url)
        storage: StorageAdapter = get_media_storage(conn)
        stored = storage.put_object(
            f"oral/results/{row['id']}.mp4", content, content_type="video/mp4"
        )
    except Exception as exc:  # noqa: BLE001 - keep the task retryable
        logger.warning("oral result archive failed: %s", type(exc).__name__)
        return
    conn.execute(
        """
        INSERT INTO assets (
            id, project_id, kind, storage_uri, sha256, size_bytes,
            content_type, created_by_user_id
        ) VALUES (%s, %s, 'oral_video', %s, %s, %s, 'video/mp4', %s)
        """,
        (
            str(uuid4()),
            row["project_id"],
            stored.uri,
            stored.sha256,
            stored.size,
            row["owner_user_id"],
        ),
    )
    asset_id = conn.execute(
        "SELECT id FROM assets WHERE storage_uri = %s ORDER BY created_at DESC LIMIT 1",
        (stored.uri,),
    ).fetchone()
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'SUCCEEDED', result_asset_id = %s, duration_sec = %s,
            completed_at = CURRENT_TIMESTAMP, locked_by = NULL, locked_until = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (str(asset_id["id"]) if asset_id else None, duration_sec, str(row["id"])),
    )
    _finalize_oral_billing(conn, task_id=str(row["id"]), outcome="settle")
    _release_oral_queue_slot(conn, task_id=str(row["id"]))


# ---------------------------------------------------------------------------
# Clone-task refresh & listing (pull-based; no webhook)
# ---------------------------------------------------------------------------


def _clone_status_map(vendor_status: str) -> str:
    return {"WAITING": "RUNNING", "PROCESSING": "RUNNING", "DONE": "READY", "FAILED": "FAILED"}[
        vendor_status
    ]


def refresh_avatar_clone(
    conn: BusinessConnection,
    *,
    avatar_id: str,
    actor: CurrentUser,
    vendor: HiflyClient,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM oral_avatars WHERE id = %s AND owner_user_id = %s",
        (avatar_id, actor.id),
    ).fetchone()
    if row is None:
        raise OralDomainError("口播分身任务不存在")
    record = dict(row)
    if record["status"] == "RUNNING" and record["vendor_task_id"]:
        try:
            snapshot = vendor.avatar_task(str(record["vendor_task_id"]))
        except HiflyError:
            return record
        status = _clone_status_map(snapshot.status)
        error = None if status != "FAILED" else "分身制作未通过，请更换素材后重试"
        conn.execute(
            """
            UPDATE oral_avatars
            SET status = %s, vendor_avatar_id = COALESCE(%s, vendor_avatar_id),
                error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, snapshot.avatar_id, error, avatar_id),
        )
        record = dict(
            conn.execute("SELECT * FROM oral_avatars WHERE id = %s", (avatar_id,)).fetchone()
        )
    return record


def refresh_voice_clone(
    conn: BusinessConnection,
    *,
    voice_id: str,
    actor: CurrentUser,
    vendor: HiflyClient,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM oral_voices WHERE id = %s AND owner_user_id = %s",
        (voice_id, actor.id),
    ).fetchone()
    if row is None:
        raise OralDomainError("声音克隆任务不存在")
    record = dict(row)
    if record["status"] == "RUNNING" and record["vendor_task_id"]:
        try:
            snapshot = vendor.voice_task(str(record["vendor_task_id"]))
        except HiflyError:
            return record
        status = _clone_status_map(snapshot.status)
        error = None if status != "FAILED" else "声音克隆未通过，请更换音频后重试"
        conn.execute(
            """
            UPDATE oral_voices
            SET status = %s, vendor_voice_id = COALESCE(%s, vendor_voice_id),
                confirmed = %s, error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, snapshot.voice, 1 if status == "READY" else 0, error, voice_id),
        )
        record = dict(
            conn.execute("SELECT * FROM oral_voices WHERE id = %s", (voice_id,)).fetchone()
        )
    return record


def list_avatars(
    conn: BusinessConnection, *, actor: CurrentUser, identity_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM oral_avatars
        WHERE identity_id = %s AND owner_user_id = %s
        ORDER BY created_at DESC
        """,
        (identity_id, actor.id),
    ).fetchall()
    return [dict(row) for row in rows]


def list_voices(
    conn: BusinessConnection, *, actor: CurrentUser, identity_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM oral_voices
        WHERE identity_id = %s AND owner_user_id = %s
        ORDER BY created_at DESC
        """,
        (identity_id, actor.id),
    ).fetchall()
    return [dict(row) for row in rows]


def list_oral_tasks(
    conn: BusinessConnection, *, actor: CurrentUser, limit: int = 20
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM oral_tasks
        WHERE owner_user_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (actor.id, max(1, min(100, limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def oral_price_quote(conn: BusinessConnection) -> dict[str, int]:
    return {"unit_price_fen": oral_unit_price_fen(conn)}
