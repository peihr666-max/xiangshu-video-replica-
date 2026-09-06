"""C5 publish routes: platform accounts and publish records for the studio.

Read routes ride the plain authenticated lane; every write goes through the
T21 fenced ``BusinessDbDep.write()`` exactly like the other studio routes.
"""

from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi import APIRouter

from app.auth import AuthenticatedUser, Database
from app.customer_fence import BusinessDbDep
from app.publish import (
    PublishAccountCreateRequest,
    PublishAccountDeleteResponse,
    PublishAccountListResponse,
    PublishAccountResponse,
    PublishRecordCreateRequest,
    PublishRecordDeleteResponse,
    PublishRecordListResponse,
    PublishRecordResponse,
    PublishRecordUpdateRequest,
    PublishVerifyResponse,
    cancel_record,
    create_account,
    create_record,
    delete_account,
    delete_record,
    list_accounts,
    list_records,
    request_account_verify,
    submit_record,
    update_record,
)
from app.settings import fernet_from_environment

router = APIRouter(prefix="/api/studio/publish")


def _fernet() -> Fernet:
    return fernet_from_environment()


@router.get("/accounts", response_model=PublishAccountListResponse)
def read_publish_accounts(
    conn: Database,
    actor: AuthenticatedUser,
) -> PublishAccountListResponse:
    return list_accounts(conn, actor_id=actor.id)


@router.post("/accounts", response_model=PublishAccountResponse)
def create_publish_account(
    request: PublishAccountCreateRequest,
    db: BusinessDbDep,
) -> PublishAccountResponse:
    with db.write() as (conn, actor):
        return create_account(conn, actor=actor, fernet=_fernet(), request=request)


@router.delete("/accounts/{account_id}", response_model=PublishAccountDeleteResponse)
def delete_publish_account(
    account_id: str,
    db: BusinessDbDep,
) -> PublishAccountDeleteResponse:
    with db.write() as (conn, actor):
        delete_account(conn, actor_id=actor.id, account_id=account_id)
    return PublishAccountDeleteResponse(deleted=True)


@router.post("/accounts/{account_id}/verify", response_model=PublishVerifyResponse)
def verify_publish_account(
    account_id: str,
    db: BusinessDbDep,
) -> PublishVerifyResponse:
    with db.write() as (conn, actor):
        request_account_verify(conn, actor_id=actor.id, account_id=account_id)
    return PublishVerifyResponse(submitted=True)


@router.get("/records", response_model=PublishRecordListResponse)
def read_publish_records(
    conn: Database,
    actor: AuthenticatedUser,
    status: str | None = None,
) -> PublishRecordListResponse:
    return list_records(conn, actor_id=actor.id, status=status)


@router.post("/records", response_model=PublishRecordResponse)
def create_publish_record(
    request: PublishRecordCreateRequest,
    db: BusinessDbDep,
) -> PublishRecordResponse:
    with db.write() as (conn, actor):
        return create_record(conn, actor=actor, request=request)


@router.patch("/records/{record_id}", response_model=PublishRecordResponse)
def update_publish_record(
    record_id: str,
    request: PublishRecordUpdateRequest,
    db: BusinessDbDep,
) -> PublishRecordResponse:
    with db.write() as (conn, actor):
        return update_record(conn, actor=actor, record_id=record_id, request=request)


@router.post("/records/{record_id}/submit", response_model=PublishRecordResponse)
def submit_publish_record(
    record_id: str,
    db: BusinessDbDep,
) -> PublishRecordResponse:
    with db.write() as (conn, actor):
        return submit_record(conn, actor=actor, record_id=record_id)


@router.post("/records/{record_id}/cancel", response_model=PublishRecordResponse)
def cancel_publish_record(
    record_id: str,
    db: BusinessDbDep,
) -> PublishRecordResponse:
    with db.write() as (conn, actor):
        return cancel_record(conn, actor_id=actor.id, record_id=record_id)


@router.delete("/records/{record_id}", response_model=PublishRecordDeleteResponse)
def delete_publish_record(
    record_id: str,
    db: BusinessDbDep,
) -> PublishRecordDeleteResponse:
    with db.write() as (conn, actor):
        delete_record(conn, actor_id=actor.id, record_id=record_id)
    return PublishRecordDeleteResponse(deleted=True)
