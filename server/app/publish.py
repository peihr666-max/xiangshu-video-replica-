"""C5 publish module: platform accounts, publish records and worker claims.

The studio publish page previously kept drafts in React memory with every
real action disabled. This module is the backend contract that unlocks it:

- ``publish_accounts`` hold platform creator cookies (douyin additionally the
  security_sdk risk-control material) encrypted at rest with the settings
  Fernet key; responses never contain credential material;
- ``publish_records`` persist drafts and queue real publishes against an
  owned archived video asset, with an optional material-library cover asset
  and an optional schedule;
- the worker claims queued records with a CAS lease (one publish per account
  at a time), performs the platform delivery outside any transaction, and
  writes results back fenced;
- account verification is an async worker probe that flips the
  connected/invalid status without ever exposing the cookie.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db_portable import BusinessConnection
from app.permissions import require_not_auditor
from app.publishers.base import PublishResult

logger = logging.getLogger(__name__)

PublishPlatform = Literal["douyin", "wechat_channels"]
PLATFORMS: tuple[str, ...] = ("douyin", "wechat_channels")
# 抖音创作者网页端发布除 Cookie 外还需要 security_sdk 风控材料；
# 视频号助手仅凭 Cookie 即可。
PLATFORMS_REQUIRING_SECURITY_SDK: frozenset[str] = frozenset({"douyin"})

PublishStatus = Literal["draft", "queued", "publishing", "published", "failed", "canceled"]
_DELETABLE_STATUSES: tuple[str, ...] = ("draft", "failed", "canceled")
_SUBMITTABLE_STATUSES: tuple[str, ...] = ("draft", "failed")

_MAX_ATTEMPTS = 3
_PUBLISH_LEASE_SECONDS = 900
_VERIFY_LEASE_SECONDS = 120

MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 2000
MAX_TAGS = 20
MAX_TAG_LENGTH = 30
MAX_DISPLAY_NAME_LENGTH = 60
MAX_COOKIE_LENGTH = 20000
MAX_SECURITY_SDK_LENGTH = 100000

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class PublishLeaseLostError(RuntimeError):
    pass


class PublishCredentialError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _now_text() -> str:
    return _now().strftime(_TIME_FORMAT)


def _iso_schedule_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TIME_FORMAT)


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------


class PublishAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH)
    cookie: str = Field(min_length=10, max_length=MAX_COOKIE_LENGTH)
    security_sdk: str | None = Field(default=None, max_length=MAX_SECURITY_SDK_LENGTH)


class PublishAccountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    platform: str
    display_name: str
    status: str
    last_verified_at: str | None
    error_message: str | None
    security_sdk_required: bool
    created_at: str


class PublishAccountListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: list[PublishAccountResponse]


class PublishAccountDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool


class PublishVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submitted: bool


class PublishRecordCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=64)
    platform: str
    account_id: str | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=MAX_TITLE_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    cover_asset_id: str | None = Field(default=None, max_length=64)
    schedule_at: str | None = Field(default=None, max_length=64)
    submit: bool = False


class PublishRecordUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    cover_asset_id: str | None = Field(default=None, max_length=64)
    schedule_at: str | None = Field(default=None, max_length=64)
    account_id: str | None = Field(default=None, max_length=64)


class PublishRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    platform: str
    account_id: str | None
    account_name: str | None
    title: str
    description: str
    tags: list[str]
    cover_asset_id: str | None
    schedule_at: str | None
    status: str
    platform_item_id: str | None
    short_url: str | None
    error_message: str | None
    attempts: int
    published_at: str | None
    created_at: str
    updated_at: str


class PublishRecordListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[PublishRecordResponse]


class PublishRecordDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        text = tag.strip()
        if not text:
            continue
        if len(text) > MAX_TAG_LENGTH:
            raise _bad_request("PUBLISH_TAG_TOO_LONG", f"单个话题不能超过 {MAX_TAG_LENGTH} 个字。")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _parse_schedule(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _bad_request("PUBLISH_SCHEDULE_INVALID", "定时发布时间格式无法解析。") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return _iso_schedule_text(moment)


def _require_owned_asset(
    conn: BusinessConnection,
    *,
    actor_id: str,
    asset_id: str,
    keyword: str,
    error_code: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, kind, storage_uri
        FROM assets
        WHERE id = %s AND created_by_user_id = %s
        """,
        (asset_id, actor_id),
    ).fetchone()
    if row is None:
        raise _not_found("ASSET_NOT_FOUND", "素材不存在或无权访问。")
    record = dict(row)
    if keyword not in str(record["kind"]):
        raise _bad_request(error_code, "素材类型不符合发布要求。")
    return record


def _require_owned_account(
    conn: BusinessConnection, *, actor_id: str, account_id: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM publish_accounts WHERE id = %s AND user_id = %s",
        (account_id, actor_id),
    ).fetchone()
    if row is None:
        raise _not_found("PUBLISH_ACCOUNT_NOT_FOUND", "发布账号不存在或无权访问。")
    return dict(row)


def _validate_account_for_platform(
    conn: BusinessConnection, *, actor_id: str, platform: str, account_id: str
) -> dict[str, Any]:
    account = _require_owned_account(conn, actor_id=actor_id, account_id=account_id)
    if str(account["platform"]) != platform:
        raise _bad_request("PUBLISH_ACCOUNT_PLATFORM_MISMATCH", "发布账号与发布平台不一致。")
    if str(account["status"]) == "invalid":
        raise _conflict("PUBLISH_ACCOUNT_INVALID", "发布账号登录态已失效，请重新连接。")
    return account


# ---------------------------------------------------------------------------
# Account domain
# ---------------------------------------------------------------------------


def _account_response(row: dict[str, Any]) -> PublishAccountResponse:
    platform = str(row["platform"])
    return PublishAccountResponse(
        id=str(row["id"]),
        platform=platform,
        display_name=str(row["display_name"]),
        status=str(row["status"]),
        last_verified_at=_text_or_none(row["last_verified_at"]),
        error_message=_text_or_none(row["error_message"]),
        security_sdk_required=platform in PLATFORMS_REQUIRING_SECURITY_SDK,
        created_at=str(row["created_at"]),
    )


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def create_account(
    conn: BusinessConnection,
    *,
    actor: Any,
    fernet: Fernet,
    request: PublishAccountCreateRequest,
) -> PublishAccountResponse:
    require_not_auditor(
        conn,
        actor=actor,
        action="publish.account.create",
        entity_type="publish_account",
        entity_id="new",
    )
    platform = request.platform.strip()
    if platform not in PLATFORMS:
        raise _bad_request("PUBLISH_PLATFORM_UNSUPPORTED", "不支持的发布平台。")
    if platform in PLATFORMS_REQUIRING_SECURITY_SDK and not (
        request.security_sdk and request.security_sdk.strip()
    ):
        raise _bad_request(
            "PUBLISH_SECURITY_SDK_REQUIRED", "该平台需要同时粘贴 security_sdk 材料。"
        )
    account_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO publish_accounts (
            id, user_id, platform, display_name, cookie_enc, security_sdk_enc, status
        ) VALUES (%s, %s, %s, %s, %s, %s, 'connected')
        """,
        (
            account_id,
            actor.id,
            platform,
            request.display_name.strip(),
            fernet.encrypt(request.cookie.strip().encode("utf-8")).decode("ascii"),
            (
                fernet.encrypt(request.security_sdk.strip().encode("utf-8")).decode("ascii")
                if request.security_sdk and request.security_sdk.strip()
                else None
            ),
        ),
    )
    row = conn.execute("SELECT * FROM publish_accounts WHERE id = %s", (account_id,)).fetchone()
    if row is None:  # pragma: no cover - insert then select in one connection
        raise RuntimeError("publish account insert was lost")
    conn.commit()
    return _account_response(dict(row))


def list_accounts(conn: BusinessConnection, *, actor_id: str) -> PublishAccountListResponse:
    rows = conn.execute(
        """
        SELECT * FROM publish_accounts
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (actor_id,),
    ).fetchall()
    return PublishAccountListResponse(accounts=[_account_response(dict(row)) for row in rows])


def delete_account(conn: BusinessConnection, *, actor_id: str, account_id: str) -> None:
    cursor = conn.execute(
        "DELETE FROM publish_accounts WHERE id = %s AND user_id = %s",
        (account_id, actor_id),
    )
    if cursor.rowcount != 1:
        raise _not_found("PUBLISH_ACCOUNT_NOT_FOUND", "发布账号不存在或无权访问。")
    conn.commit()


def request_account_verify(conn: BusinessConnection, *, actor_id: str, account_id: str) -> None:
    _require_owned_account(conn, actor_id=actor_id, account_id=account_id)
    conn.execute(
        """
        UPDATE publish_accounts SET verify_requested = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND user_id = %s
        """,
        (account_id, actor_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Record domain
# ---------------------------------------------------------------------------


def _record_response(row: dict[str, Any]) -> PublishRecordResponse:
    tags_raw = row.get("tags_json") if isinstance(row, dict) else None
    try:
        tags = json.loads(str(tags_raw or "[]"))
    except json.JSONDecodeError:
        tags = []
    return PublishRecordResponse(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        platform=str(row["platform"]),
        account_id=_text_or_none(row.get("account_id")),
        account_name=_text_or_none(row.get("account_name")),
        title=str(row["title"]),
        description=str(row["description"]),
        tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
        cover_asset_id=_text_or_none(row.get("cover_asset_id")),
        schedule_at=_text_or_none(row.get("schedule_at")),
        status=str(row["status"]),
        platform_item_id=_text_or_none(row.get("platform_item_id")),
        short_url=_text_or_none(row.get("short_url")),
        error_message=_text_or_none(row.get("error_message")),
        attempts=int(row["attempt_count"]),
        published_at=_text_or_none(row.get("published_at")),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


_RECORD_SELECT = """
    SELECT record.*, account.display_name AS account_name
    FROM publish_records AS record
    LEFT JOIN publish_accounts AS account ON account.id = record.account_id
    WHERE record.id = %s AND record.user_id = %s
"""


def _load_record(conn: BusinessConnection, *, actor_id: str, record_id: str) -> dict[str, Any]:
    row = conn.execute(_RECORD_SELECT, (record_id, actor_id)).fetchone()
    if row is None:
        raise _not_found("PUBLISH_RECORD_NOT_FOUND", "发布记录不存在或无权访问。")
    return dict(row)


def create_record(
    conn: BusinessConnection,
    *,
    actor: Any,
    request: PublishRecordCreateRequest,
) -> PublishRecordResponse:
    require_not_auditor(
        conn,
        actor=actor,
        action="publish.record.create",
        entity_type="publish_record",
        entity_id="new",
    )
    platform = request.platform.strip()
    if platform not in PLATFORMS:
        raise _bad_request("PUBLISH_PLATFORM_UNSUPPORTED", "不支持的发布平台。")
    _require_owned_asset(
        conn,
        actor_id=actor.id,
        asset_id=request.asset_id,
        keyword="video",
        error_code="PUBLISH_ASSET_NOT_VIDEO",
    )
    cover_asset_id = request.cover_asset_id
    if cover_asset_id:
        _require_owned_asset(
            conn,
            actor_id=actor.id,
            asset_id=cover_asset_id,
            keyword="image",
            error_code="PUBLISH_COVER_NOT_IMAGE",
        )
    account_id = request.account_id
    if account_id:
        _validate_account_for_platform(
            conn, actor_id=actor.id, platform=platform, account_id=account_id
        )
    schedule_at = _parse_schedule(request.schedule_at) if request.schedule_at else None
    if request.submit and not account_id:
        raise _bad_request("PUBLISH_ACCOUNT_REQUIRED", "发布前需要先选择已连接的发布账号。")

    record_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO publish_records (
            id, user_id, asset_id, platform, account_id, title, description,
            tags_json, cover_asset_id, schedule_at, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            record_id,
            actor.id,
            request.asset_id,
            platform,
            account_id,
            request.title.strip(),
            request.description.strip(),
            json.dumps(_clean_tags(request.tags), ensure_ascii=False),
            cover_asset_id,
            schedule_at,
            "queued" if request.submit else "draft",
        ),
    )
    response = _record_response(_load_record(conn, actor_id=actor.id, record_id=record_id))
    conn.commit()
    return response


def list_records(
    conn: BusinessConnection,
    *,
    actor_id: str,
    status: str | None = None,
) -> PublishRecordListResponse:
    clauses = ["record.user_id = %s"]
    parameters: list[object] = [actor_id]
    if status:
        clauses.append("record.status = %s")
        parameters.append(status)
    rows = conn.execute(
        f"""
        SELECT record.*, account.display_name AS account_name
        FROM publish_records AS record
        LEFT JOIN publish_accounts AS account ON account.id = record.account_id
        WHERE {" AND ".join(clauses)}
        ORDER BY record.created_at DESC, record.id DESC
        """,  # noqa: S608 - clause list is fixed internal literals
        tuple(parameters),
    ).fetchall()
    return PublishRecordListResponse(records=[_record_response(dict(row)) for row in rows])


def update_record(
    conn: BusinessConnection,
    *,
    actor: Any,
    record_id: str,
    request: PublishRecordUpdateRequest,
) -> PublishRecordResponse:
    require_not_auditor(
        conn,
        actor=actor,
        action="publish.record.update",
        entity_type="publish_record",
        entity_id=record_id,
    )
    record = _load_record(conn, actor_id=actor.id, record_id=record_id)
    if str(record["status"]) != "draft":
        raise _conflict("PUBLISH_RECORD_NOT_DRAFT", "只有草稿状态的发布记录可以编辑。")

    updates: dict[str, object] = {}
    if "title" in request.model_fields_set and request.title is not None:
        updates["title"] = request.title.strip()
    if "description" in request.model_fields_set and request.description is not None:
        updates["description"] = request.description.strip()
    if "tags" in request.model_fields_set and request.tags is not None:
        updates["tags_json"] = json.dumps(_clean_tags(request.tags), ensure_ascii=False)
    if "cover_asset_id" in request.model_fields_set:
        if request.cover_asset_id:
            _require_owned_asset(
                conn,
                actor_id=actor.id,
                asset_id=request.cover_asset_id,
                keyword="image",
                error_code="PUBLISH_COVER_NOT_IMAGE",
            )
        updates["cover_asset_id"] = request.cover_asset_id
    if "schedule_at" in request.model_fields_set:
        updates["schedule_at"] = (
            _parse_schedule(request.schedule_at) if request.schedule_at else None
        )
    if "account_id" in request.model_fields_set and request.account_id:
        _validate_account_for_platform(
            conn,
            actor_id=actor.id,
            platform=str(record["platform"]),
            account_id=request.account_id,
        )
        updates["account_id"] = request.account_id

    if updates:
        assignments = ", ".join(f"{column} = %s" for column in updates)
        conn.execute(
            f"""
            UPDATE publish_records SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            """,  # noqa: S608 - assignments come from fixed field whitelist
            (*updates.values(), record_id, actor.id),
        )
    response = _record_response(_load_record(conn, actor_id=actor.id, record_id=record_id))
    conn.commit()
    return response


def _queue_record(conn: BusinessConnection, *, actor_id: str, record_id: str) -> dict[str, Any]:
    record = _load_record(conn, actor_id=actor_id, record_id=record_id)
    if str(record["status"]) not in _SUBMITTABLE_STATUSES:
        raise _conflict("PUBLISH_RECORD_NOT_SUBMITTABLE", "当前状态不能发布。")
    account_id = record.get("account_id")
    if not account_id:
        raise _bad_request("PUBLISH_ACCOUNT_REQUIRED", "发布前需要先选择已连接的发布账号。")
    _validate_account_for_platform(
        conn,
        actor_id=actor_id,
        platform=str(record["platform"]),
        account_id=str(account_id),
    )
    if int(record["attempt_count"]) >= _MAX_ATTEMPTS:
        raise _conflict(
            "PUBLISH_ATTEMPTS_EXHAUSTED",
            f"该记录已尝试 {_MAX_ATTEMPTS} 次发布，请新建发布记录。",
        )
    conn.execute(
        """
        UPDATE publish_records SET status = 'queued', error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND user_id = %s AND status IN ('draft', 'failed')
        """,
        (record_id, actor_id),
    )
    queued = _load_record(conn, actor_id=actor_id, record_id=record_id)
    conn.commit()
    return queued


def submit_record(conn: BusinessConnection, *, actor: Any, record_id: str) -> PublishRecordResponse:
    require_not_auditor(
        conn,
        actor=actor,
        action="publish.record.submit",
        entity_type="publish_record",
        entity_id=record_id,
    )
    return _record_response(_queue_record(conn, actor_id=actor.id, record_id=record_id))


def cancel_record(
    conn: BusinessConnection, *, actor_id: str, record_id: str
) -> PublishRecordResponse:
    cursor = conn.execute(
        """
        UPDATE publish_records SET status = 'canceled', lease_owner = NULL,
            lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND user_id = %s AND status = 'queued'
        """,
        (record_id, actor_id),
    )
    if cursor.rowcount != 1:
        raise _conflict("PUBLISH_RECORD_NOT_CANCELLABLE", "只有排队中的发布可以取消。")
    response = _record_response(_load_record(conn, actor_id=actor_id, record_id=record_id))
    conn.commit()
    return response


def delete_record(conn: BusinessConnection, *, actor_id: str, record_id: str) -> None:
    record = _load_record(conn, actor_id=actor_id, record_id=record_id)
    if str(record["status"]) not in _DELETABLE_STATUSES:
        raise _conflict("PUBLISH_RECORD_NOT_DELETABLE", "排队中的发布请先取消，已发布的记录保留。")
    conn.execute(
        "DELETE FROM publish_records WHERE id = %s AND user_id = %s",
        (record_id, actor_id),
    )
    conn.commit()


def published_total(
    conn: BusinessConnection,
    *,
    actor_id: str,
    scoped_to_owner: bool,
) -> int:
    clause = (
        "WHERE status = 'published' AND user_id = %s"
        if scoped_to_owner
        else ("WHERE status = 'published'")
    )
    parameters: tuple[object, ...] = (actor_id,) if scoped_to_owner else ()
    row = conn.execute(
        f"SELECT COUNT(*) AS total FROM publish_records {clause}",  # noqa: S608
        parameters,
    ).fetchone()
    return int(row["total"]) if row is not None else 0


# ---------------------------------------------------------------------------
# Worker claims / finalizers (mirror the oral_worker CAS pattern)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishLease:
    kind: Literal["account_verify", "publish"]
    record_id: str
    worker_id: str
    lease_token: str
    attempt_count: int
    row: dict[str, Any]


def _quarantine_expired_publishes(conn: BusinessConnection, now_text: str) -> None:
    conn.execute(
        """
        UPDATE publish_records
        SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
            error_message = %s, updated_at = CURRENT_TIMESTAMP
        WHERE status = 'publishing' AND lease_expires_at <= %s
        """,
        ("发布执行中断，请重新发布", now_text),
    )
    conn.execute(
        """
        UPDATE publish_accounts
        SET verify_requested = 0, lease_owner = NULL, lease_expires_at = NULL,
            error_message = %s, updated_at = CURRENT_TIMESTAMP
        WHERE verify_requested = 1 AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= %s
        """,
        ("登录态校验中断，请重新发起验证", now_text),
    )


def _claim(
    conn: BusinessConnection,
    *,
    kind: Literal["account_verify", "publish"],
    table: str,
    current_state_sql: str,
    current_state_params: tuple[object, ...],
    claimed_assignments: str,
    claimed_row_updates: dict[str, object],
    candidate_sql: str,
    candidate_params: tuple[object, ...],
    worker_id: str,
    lease_seconds: int,
    now: datetime,
) -> PublishLease | None:
    now_text = now.strftime(_TIME_FORMAT)
    expires_text = (now + timedelta(seconds=lease_seconds)).strftime(_TIME_FORMAT)
    with conn:
        row = conn.execute(
            f"{candidate_sql} FOR UPDATE SKIP LOCKED",  # noqa: S608 - fixed literal
            candidate_params,
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        lease_token = uuid4().hex
        claimed = conn.execute(
            f"""
            UPDATE {table}
            SET {claimed_assignments}, lease_owner = %s, lease_expires_at = %s,
                attempt_count = attempt_count + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND ({current_state_sql})
              AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
            RETURNING attempt_count
            """,  # noqa: S608 - table/assignments are fixed internal literals
            (
                lease_token,
                expires_text,
                str(record["id"]),
                *current_state_params,
                now_text,
            ),
        ).fetchone()
        if claimed is None:
            return None
        record["lease_owner"] = lease_token
        record["attempt_count"] = int(claimed["attempt_count"])
        record.update(claimed_row_updates)
        return PublishLease(
            kind=kind,
            record_id=str(record["id"]),
            worker_id=worker_id,
            lease_token=lease_token,
            attempt_count=int(claimed["attempt_count"]),
            row=record,
        )


_PUBLISH_CANDIDATE_SQL = """
    SELECT * FROM publish_records
    WHERE status = 'queued'
      AND account_id IS NOT NULL
      AND (schedule_at IS NULL OR schedule_at <= %s)
      AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
      AND NOT EXISTS (
          SELECT 1 FROM publish_records AS active
          WHERE active.status = 'publishing'
            AND active.account_id = publish_records.account_id
      )
    ORDER BY COALESCE(schedule_at, created_at), created_at, id
    LIMIT 1
"""

_VERIFY_CANDIDATE_SQL = """
    SELECT * FROM publish_accounts
    WHERE verify_requested = 1
      AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
    ORDER BY created_at, id
    LIMIT 1
"""


def claim_publish_work(
    conn: BusinessConnection,
    *,
    worker_id: str,
    lease_seconds: int = _PUBLISH_LEASE_SECONDS,
    now: datetime | None = None,
) -> PublishLease | None:
    """Claim one queued publish; expires-quarantine first, one per account."""
    moment = now or _now()
    now_text = moment.strftime(_TIME_FORMAT)
    with conn:
        _quarantine_expired_publishes(conn, now_text)
    return _claim(
        conn,
        kind="publish",
        table="publish_records",
        current_state_sql="status = 'queued'",
        current_state_params=(),
        claimed_assignments="status = 'publishing'",
        claimed_row_updates={"status": "publishing"},
        candidate_sql=_PUBLISH_CANDIDATE_SQL,
        candidate_params=(now_text, now_text),
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        now=moment,
    )


def claim_account_verify_work(
    conn: BusinessConnection,
    *,
    worker_id: str,
    lease_seconds: int = _VERIFY_LEASE_SECONDS,
    now: datetime | None = None,
) -> PublishLease | None:
    moment = now or _now()
    now_text = moment.strftime(_TIME_FORMAT)
    with conn:
        _quarantine_expired_publishes(conn, now_text)
    return _claim(
        conn,
        kind="account_verify",
        table="publish_accounts",
        current_state_sql="verify_requested = 1",
        current_state_params=(),
        claimed_assignments="status = status",
        claimed_row_updates={},
        candidate_sql=_VERIFY_CANDIDATE_SQL,
        candidate_params=(now_text,),
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        now=moment,
    )


def prepare_publish_work(
    conn: BusinessConnection,
    lease: PublishLease,
    *,
    fernet: Fernet,
) -> PublishLease:
    """Load immutable delivery inputs (and decrypt credentials) under the lease."""
    fetched = conn.execute(
        """
        SELECT record.*, account.cookie_enc, account.security_sdk_enc,
               video.storage_uri AS video_storage_uri,
               cover.storage_uri AS cover_storage_uri
        FROM publish_records AS record
        JOIN publish_accounts AS account ON account.id = record.account_id
        JOIN assets AS video ON video.id = record.asset_id
        LEFT JOIN assets AS cover ON cover.id = record.cover_asset_id
        WHERE record.id = %s AND record.lease_owner = %s
          AND record.attempt_count = %s
        """,
        (lease.record_id, lease.lease_token, lease.attempt_count),
    ).fetchone()
    if fetched is None:
        raise PublishLeaseLostError("publish lease was lost before preparation")
    row = dict(fetched)
    try:
        row["cookie"] = fernet.decrypt(str(row["cookie_enc"]).encode("ascii")).decode("utf-8")
        sdk_enc = row["security_sdk_enc"]
        row["security_sdk"] = (
            fernet.decrypt(str(sdk_enc).encode("ascii")).decode("utf-8") if sdk_enc else None
        )
    except InvalidToken as exc:
        raise PublishCredentialError("publish credentials cannot be decrypted") from exc
    return PublishLease(
        kind=lease.kind,
        record_id=lease.record_id,
        worker_id=lease.worker_id,
        lease_token=lease.lease_token,
        attempt_count=lease.attempt_count,
        row=row,
    )


def finalize_publish_work(
    conn: BusinessConnection,
    *,
    lease: PublishLease,
    result: PublishResult,
) -> None:
    """CAS one publish result; a failed auth flips the account to invalid."""
    with conn:
        if result.status == "published":
            cursor = conn.execute(
                """
                UPDATE publish_records
                SET status = 'published', platform_item_id = %s, short_url = %s,
                    error_message = NULL, published_at = %s,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'publishing' AND lease_owner = %s
                  AND attempt_count = %s
                """,
                (
                    result.item_id,
                    result.short_url,
                    _now_text(),
                    lease.record_id,
                    lease.lease_token,
                    lease.attempt_count,
                ),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE publish_records
                SET status = 'failed', error_message = %s,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'publishing' AND lease_owner = %s
                  AND attempt_count = %s
                """,
                (
                    result.message or "发布失败",
                    lease.record_id,
                    lease.lease_token,
                    lease.attempt_count,
                ),
            )
        if cursor.rowcount != 1:
            raise PublishLeaseLostError("publish finalize lease was lost")
        if result.account_invalid:
            account_id = lease.row.get("account_id")
            if account_id:
                conn.execute(
                    """
                    UPDATE publish_accounts SET status = 'invalid',
                        error_message = %s, verify_requested = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (result.message or "登录态已失效", str(account_id)),
                )


def finalize_account_verify(
    conn: BusinessConnection,
    *,
    lease: PublishLease,
    ok: bool,
    message: str | None = None,
) -> None:
    with conn:
        cursor = conn.execute(
            """
            UPDATE publish_accounts
            SET verify_requested = 0, status = %s, last_verified_at = %s,
                error_message = %s, lease_owner = NULL, lease_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND verify_requested = 1 AND lease_owner = %s
              AND attempt_count = %s
            """,
            (
                "connected" if ok else "invalid",
                _now_text(),
                None if ok else (message or "登录态校验未通过"),
                lease.record_id,
                lease.lease_token,
                lease.attempt_count,
            ),
        )
        if cursor.rowcount != 1:
            raise PublishLeaseLostError("account verify lease was lost")
