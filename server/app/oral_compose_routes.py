from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, Database
from app.customer_fence import BusinessDbDep
from app.oral_composer import composition_capabilities
from app.oral_compositions import (
    CompositionConflictError,
    CompositionDomainError,
    cancel_composition,
    create_composition,
    list_compositions,
    read_composition,
    retry_composition,
)
from app.permissions import require_not_auditor

router = APIRouter(prefix="/api/oral")


class TemplateResponse(BaseModel):
    id: Literal["bottom_caption", "center_banner", "top_title"]
    title: str
    description: str


class CapabilityResponse(BaseModel):
    available: bool
    reason: str | None
    templates: list[TemplateResponse]


class CompositionResponse(BaseModel):
    id: str
    oral_task_id: str
    template: Literal["bottom_caption", "center_banner", "top_title"]
    text: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    result_asset_id: str | None
    is_active: bool
    error_message: str | None
    created_at: str
    updated_at: str
    replayed: bool | None = None


class CompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["bottom_caption", "center_banner", "top_title"]
    text: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


TEMPLATE_DETAILS = [
    TemplateResponse(id="bottom_caption", title="底部大字", description="底部安全区高对比大字幕"),
    TemplateResponse(id="center_banner", title="居中色带", description="画面中部半透明色带标题"),
    TemplateResponse(id="top_title", title="顶部标题", description="顶部安全区醒目标题"),
]


def _guard(exc: CompositionDomainError) -> HTTPException:
    code = (
        "ORAL_COMPOSITION_CONFLICT"
        if isinstance(exc, CompositionConflictError)
        else "ORAL_COMPOSITION_INVALID"
    )
    return HTTPException(
        409 if isinstance(exc, CompositionConflictError) else 422,
        detail={"code": code, "message": str(exc)},
    )


def _public(row: dict[str, object]) -> CompositionResponse:
    return CompositionResponse.model_validate(row)


@router.get("/compose-capabilities", response_model=CapabilityResponse)
def capabilities() -> CapabilityResponse:
    result = composition_capabilities()
    return CapabilityResponse(
        available=result.available,
        reason=None if result.available else "; ".join(result.reasons),
        templates=TEMPLATE_DETAILS,
    )


@router.post(
    "/tasks/{oral_task_id}/compositions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CompositionResponse,
)
def create(
    oral_task_id: str, request: CompositionRequest, db: BusinessDbDep
) -> CompositionResponse:
    capability = composition_capabilities()
    if not capability.available:
        raise HTTPException(
            503,
            detail={
                "code": "ORAL_COMPOSITION_UNAVAILABLE",
                "message": "; ".join(capability.reasons),
            },
        )
    try:
        with db.write() as (conn, actor):
            require_not_auditor(
                conn,
                actor=actor,
                action="oral.composition.create",
                entity_type="oral_task",
                entity_id=oral_task_id,
            )
            row = create_composition(
                conn,
                actor=actor,
                oral_task_id=oral_task_id,
                template=request.template,
                text=request.text,
                idempotency_key=request.idempotency_key,
            )
    except CompositionDomainError as exc:
        raise _guard(exc) from exc
    return _public(row)


@router.get(
    "/tasks/{oral_task_id}/compositions",
    response_model=list[CompositionResponse],
)
def list_for_task(
    oral_task_id: str, conn: Database, actor: AuthenticatedUser
) -> list[CompositionResponse]:
    return [_public(row) for row in list_compositions(conn, actor=actor, oral_task_id=oral_task_id)]


@router.get("/compositions/{composition_id}", response_model=CompositionResponse)
def read(composition_id: str, conn: Database, actor: AuthenticatedUser) -> CompositionResponse:
    try:
        return _public(read_composition(conn, actor=actor, composition_id=composition_id))
    except CompositionDomainError as exc:
        raise HTTPException(404, detail={"code": "ORAL_COMPOSITION_NOT_FOUND"}) from exc


@router.post("/compositions/{composition_id}/cancel", response_model=CompositionResponse)
def cancel(composition_id: str, db: BusinessDbDep) -> CompositionResponse:
    try:
        with db.write() as (conn, actor):
            require_not_auditor(
                conn,
                actor=actor,
                action="oral.composition.cancel",
                entity_type="oral_composition",
                entity_id=composition_id,
            )
            row = cancel_composition(conn, actor=actor, composition_id=composition_id)
    except CompositionDomainError as exc:
        raise _guard(exc) from exc
    return _public(row)


@router.post(
    "/compositions/{composition_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CompositionResponse,
)
def retry(composition_id: str, request: RetryRequest, db: BusinessDbDep) -> CompositionResponse:
    capability = composition_capabilities()
    if not capability.available:
        raise HTTPException(503, detail={"code": "ORAL_COMPOSITION_UNAVAILABLE"})
    try:
        with db.write() as (conn, actor):
            require_not_auditor(
                conn,
                actor=actor,
                action="oral.composition.retry",
                entity_type="oral_composition",
                entity_id=composition_id,
            )
            row = retry_composition(
                conn,
                actor=actor,
                composition_id=composition_id,
                idempotency_key=request.idempotency_key,
            )
    except CompositionDomainError as exc:
        raise _guard(exc) from exc
    return _public(row)
