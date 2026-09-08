"""工作台"提取文案"异步任务路由（script-from-audio）。"""

from __future__ import annotations

from typing import Literal, cast
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Request, Response, status
from pydantic import ConfigDict

from app.admin_auth_routes import AdminWriter
from app.admin_write_contract import AdminWriteContract, http_error, write_with_idempotency
from app.auth import AuthenticatedUser, CurrentUser, Database, Role
from app.customer_fence import BusinessDbDep
from app.db_portable import BusinessConnection
from app.permissions import require_project_access, write_audit
from app.script_from_audio import (
    ScriptFromAudioRequest,
    ScriptFromAudioTaskResponse,
    discard_idless_uncertain_script_from_audio_task,
    enqueue_script_from_audio_task,
    latest_script_from_audio_task,
    load_script_from_audio_task,
    script_from_audio_task_response,
)

router = APIRouter(prefix="/api")
admin_router = APIRouter(
    prefix="/api/control/admin/script-from-audio",
    tags=["admin-script-from-audio"],
)


class ScriptFromAudioReconcileRequest(AdminWriteContract):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["DISCARD"]


@router.post(
    "/projects/{project_id}/script-from-audio",
    response_model=ScriptFromAudioTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def extract_script_from_audio(
    project_id: str,
    request: ScriptFromAudioRequest,
    db: BusinessDbDep,
) -> ScriptFromAudioTaskResponse:
    with db.write() as (conn, actor):
        row = enqueue_script_from_audio_task(
            conn,
            actor=actor,
            project_id=project_id,
            source_asset_id=request.source_asset_id,
            idempotency_key=request.idempotency_key or str(uuid4()),
        )
        return script_from_audio_task_response(row)


@router.get(
    "/script-from-audio-tasks/{task_id}",
    response_model=ScriptFromAudioTaskResponse,
)
def read_script_from_audio_task(
    task_id: str,
    conn: Database,
    actor: AuthenticatedUser,
) -> ScriptFromAudioTaskResponse:
    row = load_script_from_audio_task(conn, task_id)
    require_project_access(
        conn,
        actor=actor,
        project_id=str(row["project_id"]),
        action="project.script_from_audio_read",
    )
    return script_from_audio_task_response(row)


@router.get(
    "/projects/{project_id}/script-from-audio-tasks/latest",
    response_model=ScriptFromAudioTaskResponse | None,
)
def read_latest_script_from_audio_task(
    project_id: str,
    conn: Database,
    actor: AuthenticatedUser,
) -> ScriptFromAudioTaskResponse | None:
    require_project_access(
        conn,
        actor=actor,
        project_id=project_id,
        action="project.script_from_audio_read",
    )
    row = latest_script_from_audio_task(conn, project_id=project_id)
    return None if row is None else script_from_audio_task_response(row)


@admin_router.post("/tasks/{task_id}/reconcile")
def reconcile_idless_uncertain_script_from_audio_task(
    task_id: str,
    body: ScriptFromAudioReconcileRequest,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> dict[str, object]:
    def business(raw_conn: psycopg.Connection, request_id: str) -> dict[str, object]:
        conn = BusinessConnection.postgres(raw_conn)
        row = discard_idless_uncertain_script_from_audio_task(conn, task_id=task_id)
        if row is None:
            raise http_error(
                409,
                "SCRIPT_FROM_AUDIO_TASK_NOT_ADMIN_REQUIRED",
                "Only an uncertain task without a provider task id can be discarded.",
            )
        write_audit(
            conn,
            actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            action="script_from_audio.task.reconcile",
            entity_type="script_from_audio_task",
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
            "recovery_mode": None,
            "request_id": request_id,
        }

    return write_with_idempotency(
        request,
        response,
        actor,
        body,
        business,
        success_status=200,
        unavailable_code="SCRIPT_FROM_AUDIO_RECONCILIATION_UNAVAILABLE",
        unavailable_message="Script-from-audio reconciliation requires PostgreSQL.",
    )
