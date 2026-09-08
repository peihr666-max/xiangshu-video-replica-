"""Oral digital-human routes (/api/oral/*, C1).

The dependency ``get_oral_vendor`` is the single seam tests override; routes
never surface vendor identifiers — row serialization strips ``vendor_*``
fields so the customer UI cannot leak the upstream provider name.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.admin_auth_routes import AdminWriter
from app.admin_write_contract import AdminWriteContract, write_with_idempotency
from app.auth import AuthenticatedUser, CurrentUser, Database, Role
from app.customer_fence import BusinessDbDep
from app.db_portable import BusinessConnection
from app.hifly import HiflyClient, HiflyError, hifly_client_from_settings
from app.oral import (
    OralDomainError,
    confirm_voice_clone,
    create_oral_task,
    list_avatars,
    list_oral_tasks,
    list_voices,
    oral_price_quote,
    read_avatar_clone,
    read_oral_task,
    read_voice_clone,
    reconcile_uncertain_oral_clone,
    reconcile_uncertain_oral_task,
    record_oral_clone_consent,
    start_avatar_clone,
    start_voice_clone,
)
from app.permissions import require_not_auditor, write_audit

router = APIRouter(prefix="/api/oral")
admin_router = APIRouter(prefix="/api/control/admin/oral", tags=["admin-oral"])


def get_oral_vendor(conn: Database) -> HiflyClient:
    return hifly_client_from_settings(conn)


OralVendor = Annotated[HiflyClient, Depends(get_oral_vendor)]


class OralError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


def _domain_guard(exc: OralDomainError) -> HTTPException:
    return OralError("ORAL_REQUEST_INVALID", str(exc))


def _vendor_guard(exc: HiflyError) -> HTTPException:
    return OralError("ORAL_VENDOR_UNAVAILABLE", str(exc), status_code=503)


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """Customer-facing projection: opaque task ids only, never vendor fields."""
    return {
        key: value
        for key, value in row.items()
        if not key.startswith("vendor_")
        and key not in {"idempotency_key", "subtitle_json", "reconciliation_json"}
    }


@router.get("/price")
def read_oral_price(conn: Database) -> dict[str, int]:
    try:
        return oral_price_quote(conn)
    except OralDomainError as exc:
        raise OralError("ORAL_BILLING_UNAVAILABLE", str(exc), status_code=503) from exc


# ---------------------------------------------------------------------------
# Avatars
# ---------------------------------------------------------------------------


@router.get("/avatars")
def list_oral_avatars(
    identity_id: Annotated[str, Query(min_length=1, max_length=128)],
    conn: Database,
    actor: AuthenticatedUser,
) -> list[dict[str, Any]]:
    return [_serialize(row) for row in list_avatars(conn, actor=actor, identity_id=identity_id)]


class AvatarCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=60)
    source_asset_id: str = Field(min_length=1, max_length=128)
    source_kind: Literal["VIDEO", "IMAGE"]
    consent_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)


class OralCloneConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str = Field(min_length=1, max_length=128)
    source_asset_id: str = Field(min_length=1, max_length=128)
    purpose: Literal["oral_avatar_clone", "oral_voice_clone"]
    accepted: Literal[True]


@router.post("/clone-consents")
def bind_clone_consent(
    request: OralCloneConsentRequest,
    db: BusinessDbDep,
) -> dict[str, str]:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="oral.clone_consent.bind",
            entity_type="person_identity",
            entity_id=request.identity_id,
        )
        try:
            result = record_oral_clone_consent(
                conn,
                actor=actor,
                identity_id=request.identity_id,
                source_asset_id=request.source_asset_id,
                purpose=request.purpose,
            )
        except OralDomainError as exc:
            raise _domain_guard(exc) from exc
        write_audit(
            conn,
            actor=actor,
            action="oral.clone_consent.bind",
            entity_type="asset",
            entity_id=result["consent_id"],
            metadata={
                "identity_id": request.identity_id,
                "source_asset_id": request.source_asset_id,
                "source_sha256": result["source_sha256"],
                "purpose": request.purpose,
            },
            commit=False,
        )
        conn.commit()
    return result


@router.post("/avatars", status_code=status.HTTP_202_ACCEPTED)
def create_avatar_clone(
    request: AvatarCloneRequest,
    db: BusinessDbDep,
) -> dict[str, Any]:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="oral.avatar.create",
            entity_type="person_identity",
            entity_id=request.identity_id,
        )
        try:
            result = start_avatar_clone(
                conn,
                actor=actor,
                identity_id=request.identity_id,
                title=request.title,
                source_asset_id=request.source_asset_id,
                source_kind=request.source_kind,
                consent_id=request.consent_id,
                idempotency_key=request.idempotency_key,
            )
        except OralDomainError as exc:
            raise _domain_guard(exc) from exc
        except HiflyError as exc:
            raise _vendor_guard(exc) from exc
        conn.commit()
    return {"id": result.task_id, "status": result.status}


@router.post("/avatars/{avatar_id}/refresh")
def refresh_avatar(
    avatar_id: str,
    conn: Database,
    actor: AuthenticatedUser,
) -> dict[str, Any]:
    try:
        row = read_avatar_clone(conn, avatar_id=avatar_id, actor=actor)
    except OralDomainError as exc:
        raise _domain_guard(exc) from exc
    return _serialize(row)


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------


@router.get("/voices")
def list_oral_voices(
    identity_id: Annotated[str, Query(min_length=1, max_length=128)],
    conn: Database,
    actor: AuthenticatedUser,
) -> list[dict[str, Any]]:
    return [_serialize(row) for row in list_voices(conn, actor=actor, identity_id=identity_id)]


class VoiceCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=60)
    source_asset_id: str = Field(min_length=1, max_length=128)
    consent_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)


class OralCloneReconcileRequest(AdminWriteContract):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["DISCARD"]


@router.post("/voices", status_code=status.HTTP_202_ACCEPTED)
def create_voice_clone(
    request: VoiceCloneRequest,
    db: BusinessDbDep,
) -> dict[str, Any]:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="oral.voice.create",
            entity_type="person_identity",
            entity_id=request.identity_id,
        )
        try:
            result = start_voice_clone(
                conn,
                actor=actor,
                identity_id=request.identity_id,
                title=request.title,
                source_asset_id=request.source_asset_id,
                consent_id=request.consent_id,
                idempotency_key=request.idempotency_key,
            )
        except OralDomainError as exc:
            raise _domain_guard(exc) from exc
        except HiflyError as exc:
            raise _vendor_guard(exc) from exc
        conn.commit()
    return {"id": result.task_id, "status": result.status}


@router.post("/voices/{voice_id}/refresh")
def refresh_voice(
    voice_id: str,
    conn: Database,
    actor: AuthenticatedUser,
) -> dict[str, Any]:
    try:
        row = read_voice_clone(conn, voice_id=voice_id, actor=actor)
    except OralDomainError as exc:
        raise _domain_guard(exc) from exc
    return _serialize(row)


@router.post("/voices/{voice_id}/confirm")
def confirm_voice(
    voice_id: str,
    db: BusinessDbDep,
) -> dict[str, Any]:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="oral.voice.confirm",
            entity_type="oral_voice",
            entity_id=voice_id,
        )
        try:
            row = confirm_voice_clone(conn, voice_id=voice_id, actor=actor)
        except OralDomainError as exc:
            raise _domain_guard(exc) from exc
        write_audit(
            conn,
            actor=actor,
            action="oral.voice.confirm",
            entity_type="oral_voice",
            entity_id=voice_id,
        )
        conn.commit()
    return _serialize(row)


# ---------------------------------------------------------------------------
# Oral tasks
# ---------------------------------------------------------------------------


class OralTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str = Field(min_length=1, max_length=128)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    avatar_id: str = Field(min_length=1, max_length=128)
    voice_id: str | None = Field(default=None, min_length=1, max_length=128)
    mode: Literal["TTS", "AUDIO"]
    title: str = Field(min_length=1, max_length=120)
    script_text: str | None = Field(default=None, max_length=10_000)
    audio_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    subtitle: dict[str, Any] | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class OralReconcileRequest(AdminWriteContract):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["SETTLE", "RELEASE"]


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_oral_generation_task(
    request: OralTaskRequest,
    db: BusinessDbDep,
) -> dict[str, Any]:
    with db.write() as (conn, actor):
        require_not_auditor(
            conn,
            actor=actor,
            action="oral.task.create",
            entity_type="person_identity",
            entity_id=request.identity_id,
        )
        try:
            result = create_oral_task(
                conn,
                actor=actor,
                project_id=request.project_id,
                identity_id=request.identity_id,
                avatar_id=request.avatar_id,
                voice_id=request.voice_id,
                mode=request.mode,
                title=request.title,
                script_text=request.script_text,
                audio_asset_id=request.audio_asset_id,
                subtitle=request.subtitle,
                idempotency_key=request.idempotency_key,
            )
        except OralDomainError as exc:
            raise _domain_guard(exc) from exc
        except HiflyError as exc:
            raise _vendor_guard(exc) from exc
        conn.commit()
    return {
        "id": result.task_id,
        "status": result.status,
        "estimated_cost_fen": result.estimated_cost_fen,
        "replayed": result.replayed,
    }


@router.get("/tasks")
def list_oral_generation_tasks(
    conn: Database,
    actor: AuthenticatedUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    return [_serialize(row) for row in list_oral_tasks(conn, actor=actor, limit=limit)]


@router.get("/tasks/{task_id}")
def read_oral_generation_task(
    task_id: str,
    conn: Database,
    actor: AuthenticatedUser,
) -> dict[str, Any]:
    try:
        row = read_oral_task(conn, task_id=task_id, actor=actor)
    except OralDomainError as exc:
        raise _domain_guard(exc) from exc
    return _serialize(row)


def _reconcile_admin_clone(
    *,
    request: Request,
    response: Response,
    actor: AdminWriter,
    body: OralCloneReconcileRequest,
    clone_kind: Literal["avatar", "voice"],
    clone_id: str,
) -> dict[str, object]:
    entity_type = "oral_avatar" if clone_kind == "avatar" else "oral_voice"

    def business(raw_conn: psycopg.Connection, request_id: str) -> dict[str, object]:
        conn = BusinessConnection.postgres(raw_conn)
        try:
            row = reconcile_uncertain_oral_clone(
                conn,
                clone_kind=clone_kind,
                clone_id=clone_id,
                outcome=body.outcome,
            )
        except OralDomainError as exc:
            raise OralError("ORAL_CLONE_NOT_UNCERTAIN", str(exc), status_code=409) from exc
        write_audit(
            conn,
            actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            action=f"oral.{clone_kind}.reconcile",
            entity_type=entity_type,
            entity_id=clone_id,
            metadata={
                "outcome": body.outcome,
                "reason": body.reason.strip(),
                "request_id": request_id,
                "admin_session_id": actor.session_id,
            },
            commit=False,
        )
        return {
            "id": str(row["id"]),
            "kind": clone_kind,
            "status": str(row["status"]),
            "request_id": request_id,
        }

    return write_with_idempotency(
        request,
        response,
        actor,
        body,
        business,
        success_status=200,
        unavailable_code="ORAL_RECONCILIATION_UNAVAILABLE",
        unavailable_message="Oral clone reconciliation requires the PostgreSQL runtime.",
    )


@admin_router.post("/avatars/{avatar_id}/reconcile")
def reconcile_avatar_clone(
    avatar_id: str,
    body: OralCloneReconcileRequest,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> dict[str, object]:
    return _reconcile_admin_clone(
        request=request,
        response=response,
        actor=actor,
        body=body,
        clone_kind="avatar",
        clone_id=avatar_id,
    )


@admin_router.post("/voices/{voice_id}/reconcile")
def reconcile_voice_clone(
    voice_id: str,
    body: OralCloneReconcileRequest,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> dict[str, object]:
    return _reconcile_admin_clone(
        request=request,
        response=response,
        actor=actor,
        body=body,
        clone_kind="voice",
        clone_id=voice_id,
    )


@admin_router.post("/tasks/{task_id}/reconcile")
def reconcile_oral_generation_task(
    task_id: str,
    body: OralReconcileRequest,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> dict[str, object]:
    def business(raw_conn: psycopg.Connection, request_id: str) -> dict[str, object]:
        conn = BusinessConnection.postgres(raw_conn)
        try:
            row = reconcile_uncertain_oral_task(conn, task_id=task_id, outcome=body.outcome)
        except OralDomainError as exc:
            raise OralError("ORAL_TASK_NOT_UNCERTAIN", str(exc), status_code=409) from exc
        write_audit(
            conn,
            actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            action="oral.task.reconcile",
            entity_type="oral_task",
            entity_id=task_id,
            metadata={
                "outcome": body.outcome,
                "reason": body.reason.strip(),
                "request_id": request_id,
                "admin_session_id": actor.session_id,
            },
            commit=False,
        )
        return {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "outcome": body.outcome,
            "request_id": request_id,
        }

    return write_with_idempotency(
        request,
        response,
        actor,
        body,
        business,
        success_status=200,
        unavailable_code="ORAL_RECONCILIATION_UNAVAILABLE",
        unavailable_message="Oral task reconciliation requires the PostgreSQL runtime.",
    )
