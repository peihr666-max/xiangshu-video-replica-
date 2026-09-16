"""Owner-scoped, encrypted accounts for web QR login; no credentials in DTOs."""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db_portable import BusinessConnection

Platform = Literal["douyin", "wechat_channels", "xiaohongshu"]


class BrowserLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Platform
    account_id: str | None = Field(default=None, max_length=64)


class BrowserAccount(BaseModel):
    id: str
    platform: Platform
    platform_user_id: str
    username: str
    verified_at: int


def account_response(row: Any) -> BrowserAccount:
    return BrowserAccount(
        id=row["id"],
        platform=row["platform"],
        platform_user_id=row["platform_user_id"],
        username=row["username"],
        verified_at=int(row["verified_at"].timestamp()),
    )


def list_browser_accounts(conn: BusinessConnection, owner: str) -> list[BrowserAccount]:
    return [
        account_response(row)
        for row in conn.execute(
            "SELECT id,platform,platform_user_id,username,verified_at "
            "FROM publish_browser_accounts "
            "WHERE user_id=%s ORDER BY verified_at DESC,id",
            (owner,),
        ).fetchall()
    ]


def start_login(conn: BusinessConnection, owner: str, request: BrowserLoginRequest) -> str:
    # Serialize only the short slot-allocation transaction across API instances.
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('publish-browser-login-capacity'))")
    conn.execute("DELETE FROM publish_browser_logins WHERE expires_at <= clock_timestamp()")
    if conn.execute("SELECT id FROM publish_browser_logins WHERE user_id=%s", (owner,)).fetchone():
        raise HTTPException(409, "请先完成或取消当前扫码。")
    if conn.execute("SELECT count(*) AS n FROM publish_browser_logins").fetchone()["n"] >= 4:
        raise HTTPException(429, "扫码服务繁忙，请稍后重试。")
    if (
        request.account_id
        and not conn.execute(
            "SELECT id FROM publish_browser_accounts WHERE id=%s AND user_id=%s AND platform=%s",
            (request.account_id, owner, request.platform),
        ).fetchone()
    ):
        raise HTTPException(404, "发布账号不存在。")
    login_id = str(uuid4())
    conn.execute(
        "INSERT INTO publish_browser_logins(id,user_id,platform,account_id,expires_at) "
        "VALUES (%s,%s,%s,%s,clock_timestamp()+interval '5 minutes')",
        (login_id, owner, request.platform, request.account_id),
    )
    return login_id


def existing_storage(
    conn: BusinessConnection,
    owner: str,
    account_id: str | None,
    fernet: Fernet,
) -> dict[str, Any] | None:
    if account_id is None:
        return None
    row = conn.execute(
        "SELECT storage_state_enc FROM publish_browser_accounts WHERE id=%s AND user_id=%s",
        (account_id, owner),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "发布账号不存在。")
    value: dict[str, Any] = json.loads(fernet.decrypt(row["storage_state_enc"].encode()))
    return value


def save_login(
    conn: BusinessConnection,
    owner: str,
    login_id: str,
    identity: dict[str, str],
    storage: dict[str, Any],
    fernet: Fernet,
) -> BrowserAccount:
    session = conn.execute(
        "SELECT * FROM publish_browser_logins WHERE id=%s AND user_id=%s "
        "AND expires_at>clock_timestamp() FOR UPDATE",
        (login_id, owner),
    ).fetchone()
    if session is None:
        raise HTTPException(409, "扫码已取消或过期，请重新获取二维码。")
    uid, username = identity["platform_user_id"].strip(), identity["username"].strip()
    if not uid or len(uid) > 256 or not username or len(username) > 256:
        raise HTTPException(422, "平台账号信息不完整。")
    previous = None
    if session["account_id"]:
        previous = conn.execute(
            "SELECT * FROM publish_browser_accounts WHERE id=%s AND user_id=%s FOR UPDATE",
            (session["account_id"], owner),
        ).fetchone()
        if previous is None or previous["platform_user_id"] != uid:
            raise HTTPException(409, "扫码账号与原账号不同，请取消后添加新账号。")
    raw = json.dumps(storage, ensure_ascii=False).encode()
    if len(raw) > 2_000_000:
        raise HTTPException(422, "平台登录状态过大，请重新扫码。")
    row = conn.execute(
        "INSERT INTO publish_browser_accounts"
        "(id,user_id,platform,platform_user_id,username,storage_state_enc) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,platform,platform_user_id) DO UPDATE SET "
        "username=EXCLUDED.username,storage_state_enc=EXCLUDED.storage_state_enc,"
        "verified_at=clock_timestamp() "
        "RETURNING id,platform,platform_user_id,username,verified_at",
        (
            previous["id"] if previous else str(uuid4()),
            owner,
            session["platform"],
            uid,
            username,
            fernet.encrypt(raw).decode("ascii"),
        ),
    ).fetchone()
    conn.execute("DELETE FROM publish_browser_logins WHERE id=%s AND user_id=%s", (login_id, owner))
    return account_response(row)


def delete_browser_account(conn: BusinessConnection, owner: str, account_id: str) -> None:
    if (
        conn.execute(
            "DELETE FROM publish_browser_accounts WHERE id=%s AND user_id=%s",
            (account_id, owner),
        ).rowcount
        != 1
    ):
        raise HTTPException(404, "发布账号不存在。")
