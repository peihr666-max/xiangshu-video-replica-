"""CW-078 — the customer API-Key management routes (§2.5 B / §5 line 336).

``/api/customer/api-keys`` lets a customer mint, list and revoke the API Keys
their programs present on the independent lane. Management itself rides the
**customer session fence** — never an API Key (§2.2: the whitelist explicitly
excludes 密钥管理自身, so a leaked key cannot mint or revoke its own kind).

Red lines (R-A / §2.5 B):

- The plaintext ``xsk_live_...`` is returned **exactly once**, on creation
  (``CreatedApiKeyResponse.plaintext``). The list/detail responses carry only
  metadata — ``key_prefix`` and the stored ``scopes`` — and never the
  ``key_digest`` or the plaintext.
- Revoke is a soft revoke scoped to the caller's own keys: a missing key or one
  belonging to another user is the single 404 ``API_KEY_NOT_FOUND`` (no IDOR
  oracle); repeating a revoke is an idempotent 204.
- Lifecycle events land in ``audit_logs`` with the prefix and scopes only — the
  plaintext and digest are never written to any table but ``customer_api_keys``
  (and the digest never leaves it).
"""

from __future__ import annotations

import json
from uuid import uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from app.api_key_service import (
    REVOKE_OUTCOME_NOT_FOUND,
    REVOKE_OUTCOME_REVOKED,
    ApiKeyRecord,
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from app.customer_fence import (
    CustomerSessionSnapshot,
    customer_session_snapshot,
    fenced_pg_transaction,
)

router = APIRouter(prefix="/api/customer/api-keys", tags=["customer-api-keys"])

# A label is a human reminder only; bound it so a careless paste cannot store a
# megabyte per key. The plaintext/digest are never user-supplied.
API_KEY_LABEL_MAX = 100


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""


class ApiKeyRecordResponse(BaseModel):
    """Key metadata for the management view — never the plaintext or digest."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key_prefix: str
    label: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class CreatedApiKeyResponse(BaseModel):
    """The one and only response that carries the plaintext key (§2.5 B)."""

    model_config = ConfigDict(extra="forbid")

    plaintext: str
    id: str
    key_prefix: str
    label: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class ApiKeyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ApiKeyRecordResponse]
    total: int


def _require_customer_snapshot(request: Request) -> CustomerSessionSnapshot:
    """Management is session-fenced: no session token, no key management."""
    snapshot = customer_session_snapshot(request)
    if snapshot is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "SESSION_REQUIRED",
                "message": "A customer session token is required.",
            },
        )
    return snapshot


def _insert_customer_audit(
    conn: psycopg.Connection,
    *,
    user_id: str,
    action: str,
    entity_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    """Append one key-lifecycle audit row (prefix/scopes only, never secrets)."""
    conn.execute(
        "INSERT INTO audit_logs "
        "(id, actor_user_id, action, entity_type, entity_id, metadata_json) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            str(uuid4()),
            user_id,
            action,
            "api_key",
            entity_id,
            json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True),
        ),
    )


def _record_response(record: ApiKeyRecord) -> ApiKeyRecordResponse:
    return ApiKeyRecordResponse(
        id=record.id,
        key_prefix=record.key_prefix,
        label=record.label,
        scopes=list(record.scopes),
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
    )


@router.post(
    "",
    response_model=CreatedApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_api_key(
    payload: CreateApiKeyRequest,
    request: Request,
) -> CreatedApiKeyResponse:
    """Mint one API Key under the session fence; return its plaintext once."""
    label = payload.label.strip()
    if len(label) > API_KEY_LABEL_MAX:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_API_KEY_LABEL",
                "message": f"Label must contain at most {API_KEY_LABEL_MAX} characters.",
            },
        )
    snapshot = _require_customer_snapshot(request)
    with fenced_pg_transaction(snapshot) as (conn, ctx):
        plaintext, record = create_api_key(conn, user_id=ctx.user_id, label=label)
        _insert_customer_audit(
            conn,
            user_id=ctx.user_id,
            action="customer.api_key.created",
            entity_id=record.id,
            metadata={"key_prefix": record.key_prefix, "scopes": list(record.scopes)},
        )
    return CreatedApiKeyResponse(
        plaintext=plaintext,
        id=record.id,
        key_prefix=record.key_prefix,
        label=record.label,
        scopes=list(record.scopes),
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
    )


@router.get("", response_model=ApiKeyListResponse)
def list_customer_api_keys(request: Request) -> ApiKeyListResponse:
    """List this customer's keys (including revoked, as audit) — metadata only."""
    snapshot = _require_customer_snapshot(request)
    with fenced_pg_transaction(snapshot) as (conn, ctx):
        records = list_api_keys(conn, user_id=ctx.user_id)
    return ApiKeyListResponse(
        items=[_record_response(record) for record in records],
        total=len(records),
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_customer_api_key(key_id: str, request: Request) -> Response:
    """Soft-revoke one of this customer's keys; idempotent, no IDOR oracle."""
    snapshot = _require_customer_snapshot(request)
    with fenced_pg_transaction(snapshot) as (conn, ctx):
        outcome = revoke_api_key(conn, user_id=ctx.user_id, key_id=key_id)
        if outcome == REVOKE_OUTCOME_NOT_FOUND:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "API_KEY_NOT_FOUND",
                    "message": "API key does not exist.",
                },
            )
        if outcome == REVOKE_OUTCOME_REVOKED:
            _insert_customer_audit(
                conn,
                user_id=ctx.user_id,
                action="customer.api_key.revoked",
                entity_id=key_id,
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
