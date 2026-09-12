"""CW-076 — customer self-service registration.

``POST /api/customer/register`` creates a customer identity from a username
and password with NO email/phone verification (design doc Phase 4 · CW-071).
The user row (``role='customer'``, a salted scrypt password hash, and
``registration_source='self_register'``) and its wallet are created atomically
in ONE PostgreSQL transaction, so registration can never yield a
password-less or wallet-less half-account.

Security boundaries:
- The password is hashed at the boundary (``app.password_hashing``); neither
  the plaintext nor the hash is ever returned, logged or echoed in an error.
- The username is a public identity: a strict character allow-list plus a
  length floor/ceiling, normalized (trimmed) before the uniqueness check.
- PostgreSQL is the customer source of truth (CW-025): without a PG runtime
  the route fails closed with 503 — the SQLite internal lane never
  self-registers customers.

Out of scope for CW-076 (deliberately): login, failure lockout and session
issuance are CW-077; API-key credentialing is CW-078. This endpoint only
creates the credential + wallet and returns the public identity.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import timedelta

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field

from app.db_pg import get_pg_pool, pg_transaction
from app.ops_metrics import set_current_result_code
from app.password_hashing import PasswordPolicyError, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customer", tags=["customer-auth"])

# Fixed public dummy credential: unknown accounts take the same scrypt path.
_DUMMY_PASSWORD_HASH = hash_password("cw077-public-timing-padding")

REGISTER_PATH = "/api/customer/register"

# The unique index backing ``users.username`` (revision 001). A collision on
# this constraint is the only expected race and is answered 409, never 500.
USERS_USERNAME_CONSTRAINT = "users_username_key"

REGISTRATION_SOURCE_SELF = "self_register"
_CUSTOMER_ROLE = "customer"

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
# Public identity: letters, digits, dot, dash, underscore. No whitespace and
# no '@' — this lane has no email verification, so an email-shaped username
# would falsely imply one.
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _http(status: int, code: str, message: str) -> HTTPException:
    set_current_result_code(code)
    return HTTPException(status_code=status, detail={"code": code, "message": message})


class CustomerRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bounds are generous here so the business layer (not a 422) owns the
    # precise username/password policy and its stable error codes.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class CustomerRegistrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    username: str
    display_name: str


def _normalize_username(raw: str) -> str:
    """Trim and validate the public username, or raise the stable 400 code."""
    username = raw.strip()
    if not MIN_USERNAME_LENGTH <= len(username) <= MAX_USERNAME_LENGTH:
        raise _http(
            400,
            "INVALID_USERNAME",
            f"username must contain {MIN_USERNAME_LENGTH} to {MAX_USERNAME_LENGTH} characters",
        )
    if not _USERNAME_PATTERN.match(username):
        raise _http(
            400,
            "INVALID_USERNAME",
            "username may only contain letters, digits, dot, dash and underscore",
        )
    return username


@router.post("/register", response_model=CustomerRegistrationResponse, status_code=201)
def register_customer(
    body: CustomerRegistrationRequest, request: Request
) -> CustomerRegistrationResponse:
    """Create one customer account (users + wallets) from username + password."""
    username = _normalize_username(body.username)

    # Fail closed before doing any work when the PG runtime is unavailable: the
    # customer edition is PostgreSQL-only, so registration cannot proceed on the
    # SQLite internal lane (mirrors the activation route's 503 guard).
    try:
        get_pg_pool()
    except (RuntimeError, ValueError) as exc:
        raise _http(
            503,
            "REGISTRATION_SERVICE_UNAVAILABLE",
            "Customer registration requires the PostgreSQL runtime.",
        ) from exc

    # Hash BEFORE opening the transaction: scrypt is deliberately CPU/memory
    # heavy, and holding a pooled connection across it would shrink the
    # effective pool under load.
    try:
        _registration_budget(request)
        password_hash = hash_password(body.password)
    except PasswordPolicyError as exc:
        raise _http(400, "WEAK_PASSWORD", str(exc)) from exc

    user_id = str(uuid.uuid4())
    try:
        with pg_transaction() as conn:
            conn.execute(
                "INSERT INTO users "
                "(id, username, display_name, role, password_hash, registration_source) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    user_id,
                    username,
                    username,
                    _CUSTOMER_ROLE,
                    password_hash,
                    REGISTRATION_SOURCE_SELF,
                ),
            )
            # The wallet starts at zero credit; recharge (CW-066/067 lane) tops
            # it up. Creating it in the same transaction is what makes the
            # account whole — a customer without a wallet row cannot reserve or
            # spend, so a partial commit would be a broken account.
            conn.execute("INSERT INTO wallets (user_id) VALUES (%s)", (user_id,))
    except UniqueViolation as exc:
        constraint = exc.diag.constraint_name or ""
        if constraint == USERS_USERNAME_CONSTRAINT:
            raise _http(409, "USERNAME_TAKEN", "That username is already registered.") from exc
        # Any other unique violation is unexpected: let it surface as a 500
        # rather than masking it as a username conflict.
        raise

    return CustomerRegistrationResponse(user_id=user_id, username=username, display_name=username)


class CustomerPasswordLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    device_fingerprint: str = Field(min_length=16, max_length=128)
    device_platform: str = Field(default="web", min_length=1, max_length=32)
    takeover: bool = False


class CustomerPasswordLoginResponse(CustomerRegistrationResponse):
    device_id: str
    device_token: str
    session_id: str
    session_token: str
    session_epoch: int
    session_lease_expires_at: str


def _registration_budget(request: Request) -> None:
    from app.security_rate_limit import (
        DIMENSION_LOGIN_IP,
        client_ip_from_request,
        consume_rate_limit,
        login_ip_limit,
        rate_limit_window_seconds,
    )

    with pg_transaction() as conn:
        decision = consume_rate_limit(
            conn,
            dimension=DIMENSION_LOGIN_IP,
            identifier="register:" + client_ip_from_request(request),
            limit=login_ip_limit(),
            window_seconds=rate_limit_window_seconds(),
        )
    if not decision.allowed:
        raise HTTPException(
            429,
            detail={"code": "RATE_LIMITED", "message": "注册尝试过于频繁，请稍后再试。"},
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _login_budget(request: Request, username: str) -> None:
    from app.customer_device_service import highest_device_domain_key, keyed_digest
    from app.security_rate_limit import (
        DIMENSION_LOGIN_ACCOUNT,
        DIMENSION_LOGIN_IP,
        client_ip_from_request,
        consume_rate_limit,
        login_account_limit,
        login_ip_limit,
        rate_limit_window_seconds,
    )

    _, key = highest_device_domain_key()
    decisions = []
    # Commit budgets even when the subsequent password/transaction fails.
    with pg_transaction() as conn:
        for dimension, identifier, limit in (
            (DIMENSION_LOGIN_IP, "password:" + client_ip_from_request(request), login_ip_limit()),
            (
                DIMENSION_LOGIN_ACCOUNT,
                keyed_digest(key, "password:" + username),
                login_account_limit(),
            ),
        ):
            decisions.append(
                consume_rate_limit(
                    conn,
                    dimension=dimension,
                    identifier=identifier,
                    limit=limit,
                    window_seconds=rate_limit_window_seconds(),
                )
            )
    denied = [item for item in decisions if not item.allowed]
    if denied:
        raise HTTPException(
            429,
            detail={
                "code": "RATE_LIMITED",
                "message": "登录尝试过于频繁，请稍后再试。",
            },
            headers={"Retry-After": str(max(item.retry_after_seconds for item in denied))},
        )


def _password_device(
    conn: psycopg.Connection,
    *,
    user_id: str,
    body: CustomerPasswordLoginRequest,
) -> tuple[str, str]:
    from app.customer_device_service import (
        fingerprint_digests_for,
        highest_device_domain_key,
        keyed_digest,
    )

    version, key = highest_device_domain_key()
    fingerprints, fingerprint_version = fingerprint_digests_for(
        f"password-device:{user_id}:{body.device_fingerprint}",
    )
    row = conn.execute(
        "SELECT id FROM customer_devices WHERE user_id = %s AND fingerprint_hmac = ANY(%s) "
        "AND status = 'BOUND' AND activation_code_id IS NULL FOR UPDATE",
        (user_id, fingerprints),
    ).fetchone()
    device_token = secrets.token_urlsafe(32)
    token_digest = keyed_digest(key, device_token)
    if row is not None:
        device_id = str(row[0])
        conn.execute(
            "UPDATE customer_devices SET token_digest = %s, token_key_version = %s WHERE id = %s",
            (token_digest, version, device_id),
        )
    else:
        device_id = str(uuid.uuid4())
        slots = conn.execute(
            "SELECT slot_no FROM customer_devices WHERE user_id = %s AND status = 'BOUND'",
            (user_id,),
        ).fetchall()
        used = {int(item[0]) for item in slots}
        slot = next(n for n in range(1, len(used) + 2) if n not in used)
        conn.execute(
            "INSERT INTO customer_devices "
            "(id, user_id, activation_code_id, slot_no, display_name, platform, "
            "fingerprint_hmac, fingerprint_key_version, token_digest, token_key_version, "
            "fingerprint_canonical) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                device_id,
                user_id,
                slot,
                "账号登录设备",
                body.device_platform,
                fingerprints[-1],
                fingerprint_version,
                token_digest,
                version,
                fingerprints[0],
            ),
        )
    return device_id, device_token


@router.post("/login", response_model=CustomerPasswordLoginResponse)
def password_login(
    body: CustomerPasswordLoginRequest,
    request: Request,
    response: Response,
) -> CustomerPasswordLoginResponse:
    """Password -> real fenced session; never manufactures an activation code."""
    from app.activation_code_service import ActivationKeyError
    from app.customer_auth import SessionFencingError, verify_session_context
    from app.customer_device_service import (
        fingerprint_digests_for,
        highest_device_domain_key,
        keyed_digest,
    )
    from app.customer_idempotency import (
        IdempotencyKeyError,
        complete_envelope,
        customer_aead_key,
        envelope_aad,
        highest_customer_aead_key,
        idempotency_key_digests,
        insert_envelope,
        load_envelope,
        open_response,
        recovery_window_seconds,
        request_hash,
        seal_response,
    )
    from app.customer_session_service import login_session
    from app.ops_metrics import get_or_create_request_id
    from app.security_rate_limit import DIMENSION_LOGIN_ACCOUNT, record_auth_failure

    username = body.username.strip()
    key_text = request.headers.get("Idempotency-Key", "").strip()
    if not key_text or len(key_text) > 200:
        raise _http(400, "IDEMPOTENCY_KEY_REQUIRED", "请重新提交登录。")
    response.headers["Cache-Control"] = "no-store"
    try:
        get_pg_pool()
        _, device_key = highest_device_domain_key()
        aead_version, aead_key = highest_customer_aead_key()
        key_digests = idempotency_key_digests(key_text)
    except (RuntimeError, ValueError, ActivationKeyError, IdempotencyKeyError) as exc:
        raise _http(503, "SESSION_SERVICE_UNAVAILABLE", "登录服务暂不可用，请稍后重试。") from exc

    operation = "password_login"
    digest = request_hash(
        {
            "username": username,
            "password_proof": fingerprint_digests_for("password-login:" + body.password)[0][0],
            "device": body.device_fingerprint,
            "platform": body.device_platform,
            "takeover": str(body.takeover),
        }
    )
    replay_candidate = False
    with pg_transaction() as conn:
        row = conn.execute(
            "SELECT id, username, display_name, password_hash, is_active, role, "
            "registration_source "
            "FROM users WHERE username = %s",
            (username,),
        ).fetchone()
        if row is not None:
            for key_digest in key_digests:
                envelope = load_envelope(
                    conn, operation=operation, scope=str(row[0]), key_digest=key_digest
                )
                if envelope is not None and envelope.request_hash == digest:
                    replay_candidate = True
                    break
    if not replay_candidate:
        _login_budget(request, username)
    encoded = str(row[3]) if row is not None and row[3] else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(body.password, encoded)
    if (
        row is None
        or not password_matches
        or not row[4]
        or row[5] != "customer"
        or row[6] != "self_register"
    ):
        with pg_transaction() as conn:
            record_auth_failure(
                conn,
                dimension=DIMENSION_LOGIN_ACCOUNT,
                identifier=keyed_digest(device_key, "password:" + username),
                request_id=get_or_create_request_id(request),
            )
        raise _http(401, "INVALID_CREDENTIALS", "用户名或密码错误，或账号暂不可用。")

    user_id = str(row[0])
    with pg_transaction() as conn:
        # Serializes first-device creation and rechecks account revocation/password changes.
        current = conn.execute(
            "SELECT password_hash, is_active, role, registration_source FROM users "
            "WHERE id = %s FOR UPDATE",
            (user_id,),
        ).fetchone()
        if (
            current is None
            or current[0] != encoded
            or not current[1]
            or current[2] != "customer"
            or current[3] != "self_register"
        ):
            raise _http(401, "INVALID_CREDENTIALS", "用户名或密码错误，或账号暂不可用。")
        now_row = conn.execute("SELECT clock_timestamp()").fetchone()
        assert now_row is not None
        now = now_row[0]
        for key_digest in key_digests:
            envelope = load_envelope(
                conn, operation=operation, scope=user_id, key_digest=key_digest
            )
            if envelope is None:
                continue
            if envelope.request_hash != digest:
                raise _http(409, "IDEMPOTENCY_CONFLICT", "登录信息已变化，请重新提交。")
            if (
                not envelope.ciphertext
                or not envelope.key_version
                or not envelope.recovery_expires_at
            ):
                raise _http(409, "LOGIN_RETRY_EXPIRED", "请重新提交登录。")
            from datetime import datetime

            if now >= datetime.fromisoformat(str(envelope.recovery_expires_at)):
                raise _http(409, "LOGIN_RETRY_EXPIRED", "请重新提交登录。")
            try:
                restored = CustomerPasswordLoginResponse.model_validate(
                    open_response(
                        envelope.ciphertext,
                        key=customer_aead_key(envelope.key_version),
                        aad=envelope_aad(operation, user_id, key_digest),
                    )
                )
            except (IdempotencyKeyError, ValueError) as exc:
                raise _http(
                    503, "SESSION_SERVICE_UNAVAILABLE", "登录恢复服务暂不可用，请稍后重试。"
                ) from exc
            try:
                verify_session_context(conn, presentation_session_token=restored.session_token)
            except SessionFencingError as exc:
                raise _http(401, exc.code, "登录已失效，请重新登录。") from exc
            response.headers["X-Idempotent-Replay"] = "true"
            return restored

        device_id, device_token = _password_device(conn, user_id=user_id, body=body)
        result = login_session(
            conn,
            user_id=user_id,
            activation_code_id=None,
            device_id=device_id,
            presentation_session_token=None,
            request_id=get_or_create_request_id(request),
            now=now,
            takeover=body.takeover,
        )
        answer = CustomerPasswordLoginResponse(
            user_id=user_id,
            username=str(row[1]),
            display_name=str(row[2]),
            device_id=device_id,
            device_token=device_token,
            session_id=result.session_id,
            session_token=result.session_token or "",
            session_epoch=result.session_epoch,
            session_lease_expires_at=result.lease_until,
        )
        envelope_id = insert_envelope(
            conn,
            operation=operation,
            scope=user_id,
            key_digest=key_digests[0],
            request_hash=digest,
        )
        if envelope_id is None:
            raise _http(409, "IDEMPOTENCY_CONFLICT", "请重新提交登录。")
        complete_envelope(
            conn,
            envelope_id,
            ciphertext=seal_response(
                answer.model_dump(),
                key=aead_key,
                aad=envelope_aad(operation, user_id, key_digests[0]),
            ),
            key_version=aead_version,
            recovery_expires_at=(now + timedelta(seconds=recovery_window_seconds())).isoformat(),
        )
        return answer
