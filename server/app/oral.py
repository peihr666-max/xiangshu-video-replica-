"""Oral digital-human domain services (C1 / 未接通能力拆解).

Vendor-neutral by contract: no table, row, or customer-visible message may
name the upstream provider (see the red-line test in tests/test_hifly_client.py).
Polling is pull-based (no public webhook). Generation tasks reserve one wallet
credit before queueing; the worker settles success, releases terminal failure,
and retains ambiguous submissions for reconciliation without retrying them.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.auth import CurrentUser
from app.character_identity import require_current_authorization
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyError, hifly_client_from_settings
from app.media_routes import get_media_storage, storage_for_asset
from app.permissions import require_asset_access
from app.settings import SettingsRepository
from app.storage import StorageAdapter, StoredObject

logger = logging.getLogger(__name__)

ORAL_UNIT_PRICE_FEN_DEFAULT = 1000
MAX_ORAL_SCRIPT_CHARS = 10_000
ORAL_TASK_LEASE_SECONDS = 120
ORAL_POLL_SECONDS = 15

AvatarStatus = str  # PENDING/RUNNING/READY/FAILED
TaskStatus = str  # QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED


class OralDomainError(Exception):
    """Customer-safe oral-domain failure (message is UI-renderable)."""


ORAL_CLONE_PURPOSES = {"oral_avatar_clone", "oral_voice_clone"}


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
        "SELECT id, kind, storage_uri, content_type, created_by_user_id, metadata_json "
        "FROM assets WHERE id = %s",
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


def _require_clone_inputs(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    identity_id: str,
    consent_id: str,
    source_asset_id: str,
    source_kind: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = _require_own_identity(conn, actor, identity_id)
    if str(identity.get("authorization_asset_id") or "") != consent_id:
        raise OralDomainError("肖像授权与当前人物不匹配")
    consent = _asset(conn, consent_id)
    if consent is None or str(consent.get("created_by_user_id") or "") != actor.id:
        raise OralDomainError("肖像授权不存在或无权使用")
    if str(consent.get("kind") or "") not in {
        "identity_authorization",
        "character_authorization",
    }:
        raise OralDomainError("肖像授权类型不正确")
    source = _require_source_asset(
        conn, actor=actor, asset_id=source_asset_id, message="素材不存在或无权使用"
    )
    content_type = str(source.get("content_type") or "")
    expected_prefix = {"VIDEO": "video/", "IMAGE": "image/", "AUDIO": "audio/"}[source_kind]
    if not content_type.startswith(expected_prefix):
        raise OralDomainError("克隆素材类型与请求不匹配")
    try:
        consent_metadata = json.loads(str(consent.get("metadata_json") or "{}"))
        bindings = consent_metadata.get("oral_clone_consents", [])
    except (AttributeError, json.JSONDecodeError) as exc:
        raise OralDomainError("肖像授权记录无效") from exc
    purpose = "oral_voice_clone" if source_kind == "AUDIO" else "oral_avatar_clone"
    source_sha256 = str(source.get("sha256") or "")
    if len(source_sha256) != 64 or not isinstance(bindings, list):
        raise OralDomainError("肖像授权未绑定当前克隆素材")
    expected_binding = {
        "identity_id": identity_id,
        "source_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "purpose": purpose,
    }
    if not any(
        isinstance(binding, dict)
        and all(binding.get(key) == value for key, value in expected_binding.items())
        for binding in bindings
    ):
        raise OralDomainError("肖像授权未绑定当前克隆素材")
    return identity, source


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def record_oral_clone_consent(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    identity_id: str,
    source_asset_id: str,
    purpose: str,
) -> dict[str, str]:
    if purpose not in ORAL_CLONE_PURPOSES:
        raise OralDomainError("克隆授权用途不支持")
    identity = _require_own_identity(conn, actor, identity_id)
    consent_id = str(identity.get("authorization_asset_id") or "")
    consent_row = conn.execute(
        "SELECT id, kind, storage_uri, content_type, created_by_user_id, metadata_json "
        "FROM assets WHERE id = %s FOR UPDATE",
        (consent_id,),
    ).fetchone()
    consent = dict(consent_row) if consent_row is not None else None
    if consent is None or str(consent.get("created_by_user_id") or "") != actor.id:
        raise OralDomainError("肖像授权不存在或无权使用")
    if str(consent.get("kind") or "") not in {
        "identity_authorization",
        "character_authorization",
    }:
        raise OralDomainError("肖像授权类型不正确")
    source = _require_source_asset(
        conn, actor=actor, asset_id=source_asset_id, message="素材不存在或无权使用"
    )
    content_type = str(source.get("content_type") or "")
    if purpose == "oral_voice_clone" and not content_type.startswith("audio/"):
        raise OralDomainError("声音克隆授权只能绑定音频素材")
    if purpose == "oral_avatar_clone" and not content_type.startswith(("image/", "video/")):
        raise OralDomainError("分身克隆授权只能绑定图片或视频素材")
    source_sha256 = str(source.get("sha256") or "")
    if len(source_sha256) != 64:
        raise OralDomainError("素材指纹缺失，请重新上传")
    try:
        metadata = json.loads(str(consent.get("metadata_json") or "{}"))
    except json.JSONDecodeError as exc:
        raise OralDomainError("肖像授权记录无效") from exc
    if (
        not isinstance(metadata, dict)
        or metadata.get("identity_id") != identity_id
        or metadata.get("purpose") != "authorization"
    ):
        raise OralDomainError("肖像授权与当前人物不匹配")
    binding = {
        "identity_id": identity_id,
        "source_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "purpose": purpose,
    }
    bindings = metadata.get("oral_clone_consents")
    if not isinstance(bindings, list):
        bindings = []
    if binding not in bindings:
        bindings.append(binding)
    metadata["oral_clone_consents"] = bindings
    updated = conn.execute(
        "UPDATE assets SET metadata_json = %s WHERE id = %s AND created_by_user_id = %s",
        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), consent_id, actor.id),
    )
    if updated.rowcount != 1:
        raise OralDomainError("肖像授权绑定失败")
    return {
        "consent_id": consent_id,
        "identity_id": identity_id,
        "source_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "purpose": purpose,
    }


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
    consent_id: str,
    idempotency_key: str,
    vendor: HiflyClient | None = None,
) -> CloneStartResult:
    if source_kind not in {"VIDEO", "IMAGE"}:
        raise OralDomainError("分身素材类型不支持")
    _, source = _require_clone_inputs(
        conn,
        actor=actor,
        identity_id=identity_id,
        consent_id=consent_id,
        source_asset_id=source_asset_id,
        source_kind=source_kind,
    )
    clean_title = title.strip() or "口播分身"
    request_hash = _request_hash(
        {
            "identity_id": identity_id,
            "title": clean_title,
            "source_asset_id": source_asset_id,
            "source_sha256": str(source["sha256"]),
            "source_kind": source_kind,
            "consent_id": consent_id,
        }
    )
    existing = conn.execute(
        "SELECT id, status, request_hash FROM oral_avatars "
        "WHERE owner_user_id = %s AND idempotency_key = %s",
        (actor.id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if str(existing["request_hash"]) != request_hash:
            raise OralDomainError("幂等键已用于不同的分身请求")
        return CloneStartResult(task_id=str(existing["id"]), status=str(existing["status"]))
    vendor_task_id = None
    status = "PENDING"

    avatar_id = str(uuid4())
    inserted = conn.execute(
        """
        INSERT INTO oral_avatars (
            id, identity_id, owner_user_id, title, vendor_task_id,
            status, source_kind, source_asset_id, consent_id, idempotency_key, request_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (owner_user_id, idempotency_key) DO NOTHING
        RETURNING id
        """,
        (
            avatar_id,
            identity_id,
            actor.id,
            clean_title,
            vendor_task_id,
            status,
            source_kind,
            source_asset_id,
            consent_id,
            idempotency_key,
            request_hash,
        ),
    ).fetchone()
    if inserted is not None:
        return CloneStartResult(task_id=avatar_id, status=status)
    existing = conn.execute(
        "SELECT id, status, request_hash FROM oral_avatars "
        "WHERE owner_user_id = %s AND idempotency_key = %s",
        (actor.id, idempotency_key),
    ).fetchone()
    if existing is None or str(existing["request_hash"]) != request_hash:
        raise OralDomainError("幂等键已用于不同的分身请求")
    return CloneStartResult(task_id=str(existing["id"]), status=str(existing["status"]))


def start_voice_clone(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    identity_id: str,
    title: str,
    source_asset_id: str,
    consent_id: str,
    idempotency_key: str,
    vendor: HiflyClient | None = None,
) -> CloneStartResult:
    _, source = _require_clone_inputs(
        conn,
        actor=actor,
        identity_id=identity_id,
        consent_id=consent_id,
        source_asset_id=source_asset_id,
        source_kind="AUDIO",
    )
    clean_title = title.strip() or "克隆声音"
    request_hash = _request_hash(
        {
            "identity_id": identity_id,
            "title": clean_title,
            "source_asset_id": source_asset_id,
            "source_sha256": str(source["sha256"]),
            "consent_id": consent_id,
        }
    )
    existing = conn.execute(
        "SELECT id, status, request_hash FROM oral_voices "
        "WHERE owner_user_id = %s AND idempotency_key = %s",
        (actor.id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if str(existing["request_hash"]) != request_hash:
            raise OralDomainError("幂等键已用于不同的声音请求")
        return CloneStartResult(task_id=str(existing["id"]), status=str(existing["status"]))
    vendor_task_id = None
    status = "PENDING"

    voice_id = str(uuid4())
    inserted = conn.execute(
        """
        INSERT INTO oral_voices (
            id, identity_id, owner_user_id, title, vendor_task_id,
            status, source_asset_id, consent_id, idempotency_key, request_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (owner_user_id, idempotency_key) DO NOTHING
        RETURNING id
        """,
        (
            voice_id,
            identity_id,
            actor.id,
            clean_title,
            vendor_task_id,
            status,
            source_asset_id,
            consent_id,
            idempotency_key,
            request_hash,
        ),
    ).fetchone()
    if inserted is not None:
        return CloneStartResult(task_id=voice_id, status=status)
    existing = conn.execute(
        "SELECT id, status, request_hash FROM oral_voices "
        "WHERE owner_user_id = %s AND idempotency_key = %s",
        (actor.id, idempotency_key),
    ).fetchone()
    if existing is None or str(existing["request_hash"]) != request_hash:
        raise OralDomainError("幂等键已用于不同的声音请求")
    return CloneStartResult(task_id=str(existing["id"]), status=str(existing["status"]))


def _read_asset_bytes(conn: BusinessConnection, asset: dict[str, Any]) -> bytes:
    storage, key = _asset_storage_target(conn, asset)
    try:
        return storage.get_object(key)
    except Exception as exc:  # noqa: BLE001 - surfaced as a customer-safe message
        logger.warning("oral source asset read failed: %s", type(exc).__name__)
        raise OralDomainError("素材读取失败，请重新上传") from exc


def _asset_storage_target(
    conn: BusinessConnection, asset: dict[str, Any]
) -> tuple[StorageAdapter, str]:
    storage = storage_for_asset(conn, str(asset["storage_uri"]))
    key = (
        str(asset["storage_uri"]).split("/", 3)[-1]
        if "://" in str(asset["storage_uri"])
        else str(asset["storage_uri"])
    )
    return storage, key


def _extension_for(asset: dict[str, Any], source_kind: str) -> str:
    content_type = str(asset.get("content_type") or "")
    if source_kind == "IMAGE" or content_type.startswith("image/"):
        return "png"
    if content_type.endswith("webm"):
        return "webm"
    return "mp4"


def acquire_oral_clone(conn: BusinessConnection, *, worker_id: str) -> dict[str, Any] | None:
    locked_until = (datetime.now(UTC) + timedelta(seconds=ORAL_TASK_LEASE_SECONDS)).isoformat()
    for table, clone_kind in (("oral_avatars", "avatar"), ("oral_voices", "voice")):
        lease_token = str(uuid4())
        lease_expired = (
            "locked_until::timestamptz <= CURRENT_TIMESTAMP"
            if conn.is_postgres
            else "locked_until <= CURRENT_TIMESTAMP"
        )
        conn.execute(
            f"UPDATE {table} SET status = 'SUBMISSION_UNCERTAIN', locked_by = NULL, "
            "lease_token = NULL, locked_until = NULL, "
            "error_message = '提交结果未知，请重新创建克隆任务', "
            "updated_at = CURRENT_TIMESTAMP WHERE status = 'SUBMITTING' "
            f"AND {lease_expired}"
        )
        row = conn.execute(
            f"""
            UPDATE {table} SET
                status = CASE WHEN status = 'PENDING' THEN 'SUBMITTING' ELSE status END,
                locked_by = %s, lease_token = %s, locked_until = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM {table}
                WHERE status IN ('PENDING', 'RUNNING')
                  AND (locked_until IS NULL OR {lease_expired})
                ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) AND status IN ('PENDING', 'RUNNING') RETURNING *
            """,
            (worker_id, lease_token, locked_until),
        ).fetchone()
        if row is not None:
            result = dict(row)
            result["clone_kind"] = clone_kind
            return result
    return None


@dataclass(frozen=True)
class PreparedCloneWork:
    lease: dict[str, Any]
    vendor: HiflyClient
    source_storage: StorageAdapter | None
    source_key: str | None
    source_extension: str | None
    result_storage: StorageAdapter | None


@dataclass(frozen=True)
class CloneOutcome:
    status: str
    vendor_task_id: str | None = None
    vendor_resource_id: str | None = None
    demo: StoredObject | None = None
    error_message: str | None = None


def _stored_object_snapshot(stored: StoredObject | None) -> dict[str, Any] | None:
    if stored is None:
        return None
    return {
        "uri": stored.uri,
        "sha256": stored.sha256,
        "size": stored.size,
        "content_type": stored.content_type,
    }


def _clone_outcome_snapshot(outcome: CloneOutcome | None) -> str | None:
    if outcome is None:
        return None
    return json.dumps(
        {
            "status": outcome.status,
            "vendor_task_id": outcome.vendor_task_id,
            "vendor_resource_id": outcome.vendor_resource_id,
            "demo": _stored_object_snapshot(outcome.demo),
            "error_message": outcome.error_message,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _clone_status_map(status: str) -> str:
    if status == "DONE":
        return "READY"
    if status == "FAILED":
        return "FAILED"
    return "RUNNING"


def prepare_oral_clone_work(
    conn: BusinessConnection,
    *,
    lease: dict[str, Any],
    vendor: HiflyClient | None = None,
) -> PreparedCloneWork:
    active_vendor = vendor or hifly_client_from_settings(conn)
    if str(lease["status"]) != "SUBMITTING":
        return PreparedCloneWork(
            lease=dict(lease),
            vendor=active_vendor,
            source_storage=None,
            source_key=None,
            source_extension=None,
            result_storage=(get_media_storage(conn) if lease["clone_kind"] == "voice" else None),
        )
    asset = _asset(conn, str(lease["source_asset_id"]))
    if asset is None:
        raise OralDomainError("克隆素材已失效")
    source_storage, source_key = _asset_storage_target(conn, asset)
    extension = (
        _extension_for(asset, str(lease["source_kind"]))
        if lease["clone_kind"] == "avatar"
        else "mp3"
    )
    return PreparedCloneWork(
        lease=dict(lease),
        vendor=active_vendor,
        source_storage=source_storage,
        source_key=source_key,
        source_extension=extension,
        result_storage=None,
    )


def perform_oral_clone_work(work: PreparedCloneWork) -> CloneOutcome:
    lease = work.lease
    try:
        if str(lease["status"]) == "SUBMITTING":
            if (
                work.source_storage is None
                or work.source_key is None
                or work.source_extension is None
            ):
                raise OralDomainError("克隆素材已失效")
            content = work.source_storage.get_object(work.source_key)
            target = work.vendor.create_upload_url(work.source_extension)
            work.vendor.upload_file(target, content)
            if lease["clone_kind"] == "avatar":
                create = (
                    work.vendor.create_avatar_by_image
                    if lease["source_kind"] == "IMAGE"
                    else work.vendor.create_avatar_by_video
                )
                task_id = create(
                    title=str(lease["title"])[:20], file_id=target.file_id, aigc_flag=True
                )
            else:
                task_id = work.vendor.create_voice(
                    title=str(lease["title"])[:20], file_id=target.file_id
                )
            return CloneOutcome(status="RUNNING", vendor_task_id=task_id)
        snapshot: Any = (
            work.vendor.avatar_task(str(lease["vendor_task_id"]))
            if lease["clone_kind"] == "avatar"
            else work.vendor.voice_task(str(lease["vendor_task_id"]))
        )
        status = _clone_status_map(snapshot.status)
        if lease["clone_kind"] == "avatar":
            return CloneOutcome(status=status, vendor_resource_id=snapshot.avatar_id)
        demo = None
        if status == "READY":
            if not snapshot.demo_url or work.result_storage is None:
                return CloneOutcome(status="FAILED", error_message="声音试听文件缺失，请重新克隆")
            content = work.vendor.download(snapshot.demo_url)
            demo = work.result_storage.put_object(
                f"oral/voice-demos/{lease['id']}.mp3", content, content_type="audio/mpeg"
            )
        return CloneOutcome(status=status, vendor_resource_id=snapshot.voice, demo=demo)
    except HiflyError as exc:
        if str(lease["status"]) == "SUBMITTING":
            status = "FAILED" if exc.business_rejection else "SUBMISSION_UNCERTAIN"
        else:
            status = "RUNNING"
        return CloneOutcome(status=status, error_message=str(exc)[:500])
    except OralDomainError as exc:
        status = "SUBMISSION_UNCERTAIN" if str(lease["status"]) == "SUBMITTING" else "RUNNING"
        return CloneOutcome(status=status, error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001 - storage failures are explicit clone outcomes
        logger.warning("oral clone external work failed: %s", type(exc).__name__)
        if str(lease["status"]) == "RUNNING":
            return CloneOutcome(status="RUNNING", error_message="克隆结果归档失败，等待自动重试")
        return CloneOutcome(
            status="SUBMISSION_UNCERTAIN", error_message="克隆提交结果未知，等待人工对账"
        )


def finalize_oral_clone_work(
    conn: BusinessConnection, *, work: PreparedCloneWork, outcome: CloneOutcome
) -> bool:
    lease = work.lease
    table = "oral_avatars" if lease["clone_kind"] == "avatar" else "oral_voices"
    clone_id = str(lease["id"])
    lease_current = (
        "locked_until::timestamptz > CURRENT_TIMESTAMP"
        if conn.is_postgres
        else "locked_until > CURRENT_TIMESTAMP"
    )
    demo_asset_id = None
    if outcome.demo is not None:
        demo_asset_id = str(uuid5(NAMESPACE_URL, f"oral-voice-demo:{clone_id}"))
    if table == "oral_avatars":
        updated = conn.execute(
            f"UPDATE oral_avatars SET status = %s, vendor_task_id = COALESCE(%s, vendor_task_id), "
            "vendor_avatar_id = COALESCE(%s, vendor_avatar_id), error_message = %s, "
            "locked_by = NULL, lease_token = NULL, "
            "locked_until = CASE WHEN %s = 'RUNNING' "
            "THEN now() + interval '15 seconds' ELSE NULL END, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s AND lease_token = %s "
            f"AND status = %s AND {lease_current} RETURNING id",
            (
                outcome.status,
                outcome.vendor_task_id,
                outcome.vendor_resource_id,
                outcome.error_message,
                outcome.status,
                clone_id,
                str(lease["lease_token"]),
                str(lease["status"]),
            ),
        ).fetchone()
    else:
        updated = conn.execute(
            f"UPDATE oral_voices SET status = %s, vendor_task_id = COALESCE(%s, vendor_task_id), "
            "vendor_voice_id = COALESCE(%s, vendor_voice_id), "
            "demo_asset_id = COALESCE(%s, demo_asset_id), "
            "confirmed = 0, error_message = %s, locked_by = NULL, lease_token = NULL, "
            "locked_until = CASE WHEN %s = 'RUNNING' "
            "THEN now() + interval '15 seconds' ELSE NULL END, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s "
            f"AND lease_token = %s AND status = %s AND {lease_current} RETURNING id",
            (
                outcome.status,
                outcome.vendor_task_id,
                outcome.vendor_resource_id,
                demo_asset_id,
                outcome.error_message,
                outcome.status,
                clone_id,
                str(lease["lease_token"]),
                str(lease["status"]),
            ),
        ).fetchone()
    if updated is None:
        raise OralDomainError("克隆任务租约已失效")
    if outcome.demo is not None and demo_asset_id is not None:
        conn.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
            "content_type, created_by_user_id) VALUES (%s, NULL, 'oral_audio', %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (
                demo_asset_id,
                outcome.demo.uri,
                outcome.demo.sha256,
                outcome.demo.size,
                outcome.demo.content_type,
                str(lease["owner_user_id"]),
            ),
        )
    return True


def fail_claimed_oral_clone(
    conn: BusinessConnection, *, lease: dict[str, Any], cause: Exception
) -> bool:
    table = "oral_avatars" if lease["clone_kind"] == "avatar" else "oral_voices"
    lease_current = (
        "locked_until::timestamptz > CURRENT_TIMESTAMP"
        if conn.is_postgres
        else "locked_until > CURRENT_TIMESTAMP"
    )
    updated = conn.execute(
        f"UPDATE {table} SET status = 'FAILED', error_message = %s, locked_by = NULL, "
        "lease_token = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP "
        f"WHERE id = %s AND lease_token = %s AND status = %s AND {lease_current} RETURNING id",
        (
            str(cause)[:500],
            str(lease["id"]),
            str(lease["lease_token"]),
            str(lease["status"]),
        ),
    ).fetchone()
    return updated is not None


def preserve_oral_clone_outcome_for_reconciliation(
    conn: BusinessConnection,
    *,
    lease: dict[str, Any],
    outcome: CloneOutcome | None,
    cause: Exception,
) -> bool:
    table = "oral_avatars" if lease["clone_kind"] == "avatar" else "oral_voices"
    resource_column = "vendor_avatar_id" if lease["clone_kind"] == "avatar" else "vendor_voice_id"
    failure_message = (
        f"供应商结果已返回但本地终结失败：{type(cause).__name__}"
        if outcome is not None
        else f"供应商调用已开始但结果未确认：{type(cause).__name__}"
    )
    updated = conn.execute(
        f"UPDATE {table} SET status = 'SUBMISSION_UNCERTAIN', "
        "vendor_task_id = COALESCE(%s, vendor_task_id), "
        f"{resource_column} = COALESCE(%s, {resource_column}), "
        "reconciliation_json = COALESCE(%s, reconciliation_json), "
        "error_message = %s, locked_by = NULL, "
        "lease_token = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s AND lease_token = %s AND status = %s RETURNING id",
        (
            outcome.vendor_task_id if outcome else None,
            outcome.vendor_resource_id if outcome else None,
            _clone_outcome_snapshot(outcome),
            failure_message[:500],
            str(lease["id"]),
            str(lease["lease_token"]),
            str(lease["status"]),
        ),
    ).fetchone()
    return updated is not None


def run_claimed_oral_clone(
    conn: BusinessConnection,
    *,
    lease: dict[str, Any],
    worker_id: str,
    vendor: HiflyClient | None = None,
) -> str:
    if conn.is_postgres:
        raise OralDomainError("PostgreSQL 口播 worker 必须使用分段短事务执行")
    work = prepare_oral_clone_work(conn, lease=lease, vendor=vendor)
    conn.commit()
    outcome = perform_oral_clone_work(work)
    finalize_oral_clone_work(conn, work=work, outcome=outcome)
    conn.commit()
    return str(lease["id"])


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
            "SELECT id, status, identity_id, confirmed, demo_asset_id FROM oral_voices "
            "WHERE id = %s AND owner_user_id = %s",
            (effective_voice, actor.id),
        ).fetchone()
        if voice is None or str(voice["status"]) != "READY":
            raise OralDomainError("请选择已就绪的声音")
        if voice["identity_id"] != identity_id:
            raise OralDomainError("声音与人物不匹配")
        if int(voice["confirmed"] or 0) != 1 or not voice["demo_asset_id"]:
            raise OralDomainError("请先试听并确认克隆声音")
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

    request_hash = hashlib.sha256(
        json.dumps(
            {
                "identity_id": identity_id,
                "avatar_id": avatar_id,
                "voice_id": effective_voice,
                "mode": mode,
                "title": title.strip()[:120],
                "script_text": script_text,
                "audio_asset_id": audio_asset_id,
                "subtitle": subtitle,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    existing = conn.execute(
        "SELECT id, status, estimated_cost_fen, request_hash FROM oral_tasks "
        "WHERE owner_user_id = %s AND idempotency_key = %s",
        (actor.id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if existing["request_hash"] != request_hash:
            raise OralDomainError("幂等键已用于不同的口播请求")
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
    inserted = conn.execute(
        """
        INSERT INTO oral_tasks (
            id, owner_user_id, project_id, identity_id, avatar_id, voice_id, mode, title,
            script_text, audio_asset_id, subtitle_json, status,
            estimated_cost_fen, idempotency_key, request_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'QUEUED', %s, %s, %s)
        ON CONFLICT (owner_user_id, idempotency_key) DO NOTHING
        RETURNING id
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
            request_hash,
        ),
    ).fetchone()
    if inserted is None:
        existing = conn.execute(
            "SELECT id, status, estimated_cost_fen, request_hash FROM oral_tasks "
            "WHERE owner_user_id = %s AND idempotency_key = %s",
            (actor.id, idempotency_key),
        ).fetchone()
        if existing is None or str(existing["request_hash"]) != request_hash:
            raise OralDomainError("幂等键已用于不同的口播请求")
        return OralTaskCreated(
            task_id=str(existing["id"]),
            status=str(existing["status"]),
            estimated_cost_fen=int(existing["estimated_cost_fen"]),
            replayed=True,
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


def read_oral_task(conn: BusinessConnection, *, task_id: str, actor: CurrentUser) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM oral_tasks WHERE id = %s AND owner_user_id = %s",
        (task_id, actor.id),
    ).fetchone()
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
                lease_token = NULL, locked_until = NULL,
                error_message = '提交结果未知，等待人工对账',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'SUBMITTING' AND locked_until::timestamptz <= now()
            RETURNING id
            """
        ).fetchall()
        for row in expired:
            _release_oral_queue_slot(conn, task_id=str(row["id"]))
        continuation_token = str(uuid4())
        continuation = conn.execute(
            """
            UPDATE oral_tasks SET locked_by = %s, lease_token = %s, locked_until = %s,
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
            (worker_id, continuation_token, locked_until),
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
        lease_token = str(uuid4())
        row = conn.execute(
            """
            UPDATE oral_tasks SET status = 'SUBMITTING', attempt = attempt + 1,
                submitted_at = COALESCE(submitted_at::timestamptz, CURRENT_TIMESTAMP),
                locked_by = %s, lease_token = %s, locked_until = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM oral_tasks WHERE owner_user_id = %s AND status = 'QUEUED'
                ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) RETURNING *
            """,
            (worker_id, lease_token, locked_until, user_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE user_queue_cursors SET running_tasks_count = running_tasks_count + 1, "
            "last_dispatched_at = now() WHERE user_id = %s",
            (user_id,),
        )
        return dict(row)
    lease_token = str(uuid4())
    row = conn.execute(
        """
        UPDATE oral_tasks SET
            status = CASE WHEN status = 'QUEUED' THEN 'SUBMITTING' ELSE status END,
            attempt = attempt + CASE WHEN status = 'QUEUED' THEN 1 ELSE 0 END,
            locked_by = %s, lease_token = %s, locked_until = %s,
            updated_at = CURRENT_TIMESTAMP
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
        (worker_id, lease_token, locked_until),
    ).fetchone()
    conn.commit()
    return dict(row) if row is not None else None


@dataclass(frozen=True)
class PreparedOralWork:
    lease: dict[str, Any]
    vendor: HiflyClient
    audio_storage: StorageAdapter | None
    audio_key: str | None
    result_storage: StorageAdapter | None
    avatar_vendor_id: str | None
    voice_vendor_id: str | None
    subtitle: dict[str, Any] | None


@dataclass(frozen=True)
class OralOutcome:
    status: str
    vendor_task_id: str | None = None
    vendor_error_code: int | None = None
    error_message: str | None = None
    stored: StoredObject | None = None
    duration_sec: int | None = None


def _oral_outcome_snapshot(outcome: OralOutcome | None) -> str | None:
    if outcome is None:
        return None
    return json.dumps(
        {
            "status": outcome.status,
            "vendor_task_id": outcome.vendor_task_id,
            "vendor_error_code": outcome.vendor_error_code,
            "error_message": outcome.error_message,
            "stored": _stored_object_snapshot(outcome.stored),
            "duration_sec": outcome.duration_sec,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def prepare_oral_task_work(
    conn: BusinessConnection,
    *,
    lease: dict[str, Any],
    vendor: HiflyClient | None = None,
) -> PreparedOralWork:
    active_vendor = vendor or hifly_client_from_settings(conn)
    audio_storage: StorageAdapter | None = None
    audio_key: str | None = None
    avatar_vendor_id: str | None = None
    voice_vendor_id: str | None = None
    subtitle = None
    if str(lease["status"]) == "SUBMITTING":
        if lease["mode"] == "AUDIO":
            asset = _asset(conn, str(lease["audio_asset_id"]))
            if asset is None:
                raise OralDomainError("口播音频已失效，请重新上传")
            audio_storage, audio_key = _asset_storage_target(conn, asset)
        avatar_vendor_id = _vendor_avatar_id(conn, str(lease["avatar_id"]))
        voice_vendor_id = (
            _vendor_voice_id(conn, str(lease["voice_id"])) if lease["mode"] == "TTS" else None
        )
        subtitle = json.loads(str(lease["subtitle_json"])) if lease["subtitle_json"] else None
    return PreparedOralWork(
        lease=dict(lease),
        vendor=active_vendor,
        audio_storage=audio_storage,
        audio_key=audio_key,
        result_storage=get_media_storage(conn) if str(lease["status"]) == "RUNNING" else None,
        avatar_vendor_id=avatar_vendor_id,
        voice_vendor_id=voice_vendor_id,
        subtitle=subtitle,
    )


def perform_oral_task_work(work: PreparedOralWork) -> OralOutcome:
    lease = work.lease
    try:
        if str(lease["status"]) == "SUBMITTING":
            audio_target = None
            if work.audio_storage is not None and work.audio_key is not None:
                audio_content = work.audio_storage.get_object(work.audio_key)
                audio_target = work.vendor.create_upload_url("mp3")
                work.vendor.upload_file(audio_target, audio_content)
            if lease["mode"] == "TTS":
                vendor_task_id = work.vendor.create_video_by_tts(
                    voice=str(work.voice_vendor_id),
                    text=str(lease["script_text"]),
                    avatar=str(work.avatar_vendor_id),
                    title=str(lease["title"])[:20],
                    aigc_flag=True,
                    subtitle=work.subtitle,
                )
            else:
                vendor_task_id = work.vendor.create_video_by_audio(
                    avatar=str(work.avatar_vendor_id),
                    title=str(lease["title"])[:20],
                    file_id=audio_target.file_id if audio_target else None,
                    aigc_flag=True,
                )
            return OralOutcome(status="RUNNING", vendor_task_id=vendor_task_id)
        snapshot = work.vendor.video_task(str(lease["vendor_task_id"]))
        if snapshot.status == "FAILED":
            return OralOutcome(
                status="FAILED", error_message="数字人服务生成失败，请调整内容后重试"
            )
        if snapshot.status != "DONE":
            return OralOutcome(status="RUNNING")
        if not snapshot.video_url:
            return OralOutcome(status="FAILED", error_message="数字人服务未返回成片地址")
        if work.result_storage is None:
            raise OralDomainError("成片存储暂不可用")
        content = work.vendor.download(snapshot.video_url)
        stored = work.result_storage.put_object(
            f"oral/results/{lease['id']}.mp4", content, content_type="video/mp4"
        )
        return OralOutcome(status="SUCCEEDED", stored=stored, duration_sec=snapshot.duration)
    except HiflyError as exc:
        if str(lease["status"]) == "SUBMITTING":
            status = "FAILED" if exc.business_rejection else "SUBMISSION_UNCERTAIN"
        else:
            status = "RUNNING"
        return OralOutcome(
            status=status,
            vendor_error_code=exc.vendor_code,
            error_message=str(exc)[:500],
        )
    except OralDomainError as exc:
        status = "SUBMISSION_UNCERTAIN" if str(lease["status"]) == "SUBMITTING" else "RUNNING"
        return OralOutcome(status=status, error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001 - storage failure remains retryable after submit
        logger.warning("oral external work failed: %s", type(exc).__name__)
        if str(lease["status"]) == "SUBMITTING":
            return OralOutcome(
                status="SUBMISSION_UNCERTAIN",
                error_message="口播提交结果未知，等待人工对账",
            )
        return OralOutcome(status="RUNNING", error_message="成片归档失败，等待自动重试")


def finalize_oral_task_work(
    conn: BusinessConnection, *, work: PreparedOralWork, outcome: OralOutcome
) -> bool:
    lease = work.lease
    task_id = str(lease["id"])
    lease_current = (
        "locked_until::timestamptz > CURRENT_TIMESTAMP"
        if conn.is_postgres
        else "locked_until > CURRENT_TIMESTAMP"
    )
    if outcome.status in {"SUCCEEDED", "FAILED"}:
        reservation = conn.execute(
            "SELECT user_id FROM wallet_transactions WHERE oral_task_id = %s "
            "AND billing_round = 1 AND type = 'RESERVE' FOR UPDATE",
            (task_id,),
        ).fetchone()
        if reservation is None:
            raise OralDomainError("口播任务缺少预扣记录")
    result_asset_id = None
    if outcome.stored is not None:
        result_asset_id = str(uuid5(NAMESPACE_URL, f"oral-result:{task_id}"))
    completed = outcome.status in {"SUCCEEDED", "FAILED", "CANCELLED"}
    updated = conn.execute(
        f"UPDATE oral_tasks SET status = %s, vendor_task_id = COALESCE(%s, vendor_task_id), "
        "vendor_error_code = %s, error_message = %s, "
        "result_asset_id = COALESCE(%s, result_asset_id), "
        "duration_sec = COALESCE(%s, duration_sec), "
        "next_poll_at = CASE WHEN %s = 'RUNNING' THEN now() + interval '15 seconds' ELSE NULL END, "
        "completed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END, "
        "locked_by = NULL, lease_token = NULL, locked_until = NULL, updated_at = CURRENT_TIMESTAMP "
        f"WHERE id = %s AND lease_token = %s AND status = %s AND {lease_current} RETURNING id",
        (
            outcome.status,
            outcome.vendor_task_id,
            outcome.vendor_error_code,
            outcome.error_message,
            result_asset_id,
            outcome.duration_sec,
            outcome.status,
            completed,
            task_id,
            str(lease["lease_token"]),
            str(lease["status"]),
        ),
    ).fetchone()
    if updated is None:
        raise OralDomainError("口播任务租约已失效，结果需人工对账")
    if outcome.stored is not None and result_asset_id is not None:
        conn.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
            "content_type, created_by_user_id) VALUES (%s, %s, 'oral_video', %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (
                result_asset_id,
                str(lease["project_id"]),
                outcome.stored.uri,
                outcome.stored.sha256,
                outcome.stored.size,
                outcome.stored.content_type,
                str(lease["owner_user_id"]),
            ),
        )
    if outcome.status == "SUCCEEDED":
        _finalize_oral_billing(conn, task_id=task_id, outcome="settle")
        _release_oral_queue_slot(conn, task_id=task_id)
    elif outcome.status == "FAILED":
        _finalize_oral_billing(conn, task_id=task_id, outcome="release")
        _release_oral_queue_slot(conn, task_id=task_id)
    elif outcome.status == "SUBMISSION_UNCERTAIN":
        _release_oral_queue_slot(conn, task_id=task_id)
    return True


def fail_claimed_oral_task(
    conn: BusinessConnection, *, lease: dict[str, Any], cause: Exception
) -> bool:
    task_id = str(lease["id"])
    reservation = conn.execute(
        "SELECT user_id FROM wallet_transactions WHERE oral_task_id = %s "
        "AND billing_round = 1 AND type = 'RESERVE' FOR UPDATE",
        (task_id,),
    ).fetchone()
    if reservation is None:
        raise OralDomainError("口播任务缺少预扣记录")
    lease_current = (
        "locked_until::timestamptz > CURRENT_TIMESTAMP"
        if conn.is_postgres
        else "locked_until > CURRENT_TIMESTAMP"
    )
    updated = conn.execute(
        "UPDATE oral_tasks SET status = 'FAILED', error_message = %s, "
        "completed_at = CURRENT_TIMESTAMP, locked_by = NULL, lease_token = NULL, "
        "locked_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s "
        f"AND lease_token = %s AND status = %s AND {lease_current} RETURNING id",
        (str(cause)[:500], task_id, str(lease["lease_token"]), str(lease["status"])),
    ).fetchone()
    if updated is None:
        return False
    _finalize_oral_billing(conn, task_id=task_id, outcome="release")
    _release_oral_queue_slot(conn, task_id=task_id)
    return True


def preserve_oral_task_outcome_for_reconciliation(
    conn: BusinessConnection,
    *,
    lease: dict[str, Any],
    outcome: OralOutcome | None,
    cause: Exception,
) -> bool:
    failure_message = (
        f"供应商结果已返回但本地终结失败：{type(cause).__name__}"
        if outcome is not None
        else f"供应商调用已开始但结果未确认：{type(cause).__name__}"
    )
    updated = conn.execute(
        "UPDATE oral_tasks SET status = 'SUBMISSION_UNCERTAIN', "
        "vendor_task_id = COALESCE(%s, vendor_task_id), "
        "vendor_error_code = COALESCE(%s, vendor_error_code), "
        "reconciliation_json = COALESCE(%s, reconciliation_json), "
        "error_message = %s, locked_by = NULL, "
        "lease_token = NULL, locked_until = NULL, next_poll_at = NULL, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = %s "
        "AND lease_token = %s AND status = %s RETURNING id",
        (
            outcome.vendor_task_id if outcome else None,
            outcome.vendor_error_code if outcome else None,
            _oral_outcome_snapshot(outcome),
            failure_message[:500],
            str(lease["id"]),
            str(lease["lease_token"]),
            str(lease["status"]),
        ),
    ).fetchone()
    if updated is None:
        return False
    _release_oral_queue_slot(conn, task_id=str(lease["id"]))
    return True


def run_next_oral_task(
    conn: BusinessConnection,
    *,
    worker_id: str,
    vendor: HiflyClient | None = None,
    lease: dict[str, Any] | None = None,
) -> str | None:
    if conn.is_postgres:
        raise OralDomainError("PostgreSQL 口播 worker 必须使用分段短事务执行")
    lease = lease or acquire_oral_task(conn, worker_id=worker_id)
    if lease is None:
        return None
    work = prepare_oral_task_work(conn, lease=lease, vendor=vendor)
    conn.commit()
    outcome = perform_oral_task_work(work)
    finalize_oral_task_work(conn, work=work, outcome=outcome)
    conn.commit()
    return str(lease["id"])


def _reserve_oral_billing(conn: BusinessConnection, *, user_id: str, task_id: str) -> None:
    existing = conn.execute(
        "SELECT user_id FROM wallet_transactions "
        "WHERE oral_task_id = %s AND billing_round = 1 AND type = 'RESERVE' FOR UPDATE",
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


def reconcile_uncertain_oral_task(
    conn: BusinessConnection, *, task_id: str, outcome: str
) -> dict[str, Any]:
    if outcome not in {"SETTLE", "RELEASE"}:
        raise OralDomainError("人工对账结果不支持")
    row = _oral_task_row(conn, task_id)
    if row["status"] != "SUBMISSION_UNCERTAIN":
        raise OralDomainError("仅提交结果不确定的任务可人工对账")
    reservation = conn.execute(
        "SELECT 1 FROM wallet_transactions WHERE oral_task_id = %s "
        "AND billing_round = 1 AND type = 'RESERVE' FOR UPDATE",
        (task_id,),
    ).fetchone()
    if reservation is None:
        raise OralDomainError("口播任务缺少预扣记录")
    terminal_status = "FAILED" if outcome == "SETTLE" else "CANCELLED"
    message = (
        "人工确认供应商已受理并计费，成片需线下归档"
        if outcome == "SETTLE"
        else "人工确认供应商未受理，预扣已释放"
    )
    updated = conn.execute(
        "UPDATE oral_tasks SET status = %s, error_message = %s, "
        "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s AND status = 'SUBMISSION_UNCERTAIN' RETURNING id",
        (terminal_status, message, task_id),
    ).fetchone()
    if updated is None:
        raise OralDomainError("口播任务已由其他对账操作处理")
    _finalize_oral_billing(
        conn,
        task_id=task_id,
        outcome="settle" if outcome == "SETTLE" else "release",
    )
    return _oral_task_row(conn, task_id)


# ---------------------------------------------------------------------------
# Pull-based vendor refresh (no public webhook available)
# ---------------------------------------------------------------------------


def refresh_avatar_clone(
    conn: BusinessConnection,
    *,
    avatar_id: str,
    actor: CurrentUser,
    vendor: HiflyClient,
) -> dict[str, Any]:
    # Compatibility alias. Provider polling belongs exclusively to the worker.
    return read_avatar_clone(conn, avatar_id=avatar_id, actor=actor)


def read_avatar_clone(
    conn: BusinessConnection, *, avatar_id: str, actor: CurrentUser
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM oral_avatars WHERE id = %s AND owner_user_id = %s",
        (avatar_id, actor.id),
    ).fetchone()
    if row is None:
        raise OralDomainError("口播分身任务不存在")
    return dict(row)


def refresh_voice_clone(
    conn: BusinessConnection,
    *,
    voice_id: str,
    actor: CurrentUser,
    vendor: HiflyClient,
) -> dict[str, Any]:
    # Compatibility alias. Provider polling belongs exclusively to the worker.
    return read_voice_clone(conn, voice_id=voice_id, actor=actor)


def read_voice_clone(
    conn: BusinessConnection, *, voice_id: str, actor: CurrentUser
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM oral_voices WHERE id = %s AND owner_user_id = %s",
        (voice_id, actor.id),
    ).fetchone()
    if row is None:
        raise OralDomainError("声音克隆任务不存在")
    return dict(row)


def confirm_voice_clone(
    conn: BusinessConnection, *, voice_id: str, actor: CurrentUser
) -> dict[str, Any]:
    updated = conn.execute(
        "UPDATE oral_voices SET confirmed = 1, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s AND owner_user_id = %s AND status = 'READY' "
        "AND demo_asset_id IS NOT NULL RETURNING *",
        (voice_id, actor.id),
    ).fetchone()
    if updated is None:
        raise OralDomainError("声音尚未完成试听归档，暂不能确认")
    return dict(updated)


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
