"""Oral digital-human domain services (C1 / 未接通能力拆解).

Vendor-neutral by contract: no table, row, or customer-visible message may
name the upstream provider (see the red-line test in tests/test_hifly_client.py).
Polling is pull-based (no public webhook) — the status endpoints refresh from
the vendor on read, mirroring how the studio shell already polls tasks.

Wallet RESERVE/SETTLE intentionally waits for a dedicated slice: the internal
billing reconciler (BILL-03) is generation-task scoped, so oral reservations
need a task-type discriminator before they can survive it. Until then the
task carries a price snapshot only.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.auth import CurrentUser
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyError
from app.media_routes import get_media_storage, storage_for_asset
from app.settings import SettingsRepository
from app.storage import StorageAdapter

logger = logging.getLogger(__name__)

ORAL_UNIT_PRICE_FEN_DEFAULT = 1000
MAX_ORAL_SCRIPT_CHARS = 10_000

AvatarStatus = str  # PENDING/RUNNING/READY/FAILED
TaskStatus = str  # QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED


class OralDomainError(Exception):
    """Customer-safe oral-domain failure (message is UI-renderable)."""


def oral_unit_price_fen(conn: BusinessConnection) -> int:
    """Per-task list price for oral renders; admin-configurable via billing."""
    try:
        billing = SettingsRepository(conn).read_billing_settings()
    except Exception:  # noqa: BLE001 - pricing must never break task creation
        return ORAL_UNIT_PRICE_FEN_DEFAULT
    try:
        price = int(billing.get("oral_unit_price_fen", ORAL_UNIT_PRICE_FEN_DEFAULT))
    except (TypeError, ValueError):
        return ORAL_UNIT_PRICE_FEN_DEFAULT
    return price if price > 0 else ORAL_UNIT_PRICE_FEN_DEFAULT


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _identity(conn: BusinessConnection, identity_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, owner_user_id, display_name FROM person_identities WHERE id = %s",
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
    identity = _identity(conn, identity_id)
    if identity is None or identity["owner_user_id"] != actor.id:
        raise OralDomainError("人物不存在或无权使用")
    return identity


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
    asset = _asset(conn, source_asset_id)
    if asset is None:
        raise OralDomainError("素材不存在或已删除")
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
    asset = _asset(conn, source_asset_id)
    if asset is None:
        raise OralDomainError("音频素材不存在或已删除")
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
    vendor: HiflyClient,
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
        if not audio_asset_id or _asset(conn, audio_asset_id) is None:
            raise OralDomainError("请上传完整的口播音频")

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

    price = oral_unit_price_fen(conn)
    task_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO oral_tasks (
            id, owner_user_id, identity_id, avatar_id, voice_id, mode, title,
            script_text, audio_asset_id, subtitle_json, status,
            estimated_cost_fen, idempotency_key
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'QUEUED', %s, %s)
        """,
        (
            task_id,
            actor.id,
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

    _submit_oral_task(conn, task_id=task_id, vendor=vendor)
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
    except (HiflyError, OralDomainError) as exc:
        conn.execute(
            """
            UPDATE oral_tasks
            SET status = 'FAILED', error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            (str(exc)[:500], task_id),
        )
        return
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'RUNNING', vendor_task_id = %s, updated_at = CURRENT_TIMESTAMP
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
            SET status = 'FAILED', error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
                ("数字人服务生成失败，请调整内容后重试", task_id),
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
            SET status = 'FAILED', error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            ("数字人服务未返回成片地址", str(row["id"])),
        )
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
        ) VALUES (%s, NULL, 'oral_video', %s, %s, %s, 'video/mp4', %s)
        """,
        (str(uuid4()), stored.uri, stored.sha256, stored.size, row["owner_user_id"]),
    )
    asset_id = conn.execute(
        "SELECT id FROM assets WHERE storage_uri = %s ORDER BY created_at DESC LIMIT 1",
        (stored.uri,),
    ).fetchone()
    conn.execute(
        """
        UPDATE oral_tasks
        SET status = 'SUCCEEDED', result_asset_id = %s, duration_sec = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (str(asset_id["id"]) if asset_id else None, duration_sec, str(row["id"])),
    )


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
