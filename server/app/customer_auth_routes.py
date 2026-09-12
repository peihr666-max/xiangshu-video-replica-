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
import uuid

from fastapi import APIRouter, HTTPException
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field

from app.db_pg import get_pg_pool, pg_transaction
from app.ops_metrics import set_current_result_code
from app.password_hashing import PasswordPolicyError, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customer", tags=["customer-auth"])

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
def register_customer(body: CustomerRegistrationRequest) -> CustomerRegistrationResponse:
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
