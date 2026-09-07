"""HTTP contract for the Studio material library."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, Database
from app.customer_fence import BusinessDbDep
from app.materials import (
    MaterialItem,
    MaterialMediaType,
    MaterialPage,
    MaterialResolveResponse,
    MaterialSource,
    MaterialUpdateRequest,
    MaterialUploadIntentRequest,
    MaterialUploadIntentResponse,
    create_material_upload_intent,
    hide_material,
    list_materials,
    material_final_storage_key,
    persist_material_upload,
    prepare_material_upload,
    probe_material_upload,
    require_material,
    resolve_materials,
    update_material,
)
from app.media_routes import MediaStorage, api_base_url
from app.storage import StorageBackendUnavailable

router = APIRouter(prefix="/api/studio/materials", tags=["studio-materials"])
logger = logging.getLogger(__name__)


class MaterialResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_ids: list[str] = Field(min_length=1, max_length=100)


@router.get("", response_model=MaterialPage)
def read_materials(
    conn: Database,
    actor: AuthenticatedUser,
    media_type: MaterialMediaType | None = None,
    source: MaterialSource | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> MaterialPage:
    return list_materials(
        conn,
        actor=actor,
        media_type=media_type,
        source=source,
        query=q.strip() if q and q.strip() else None,
        page=page,
        page_size=page_size,
    )


@router.post("/resolve", response_model=MaterialResolveResponse)
def read_materials_by_id(
    request: MaterialResolveRequest,
    conn: Database,
    actor: AuthenticatedUser,
) -> MaterialResolveResponse:
    return resolve_materials(conn, actor=actor, material_ids=request.material_ids)


@router.post("/upload-intent", response_model=MaterialUploadIntentResponse)
def create_upload_intent(
    request: MaterialUploadIntentRequest,
    db: BusinessDbDep,
    storage: MediaStorage,
) -> MaterialUploadIntentResponse | JSONResponse:
    with db.write() as (conn, actor):
        intent = create_material_upload_intent(
            conn,
            actor=actor,
            storage=storage,
            request=request,
        )
        is_customer = actor.role == "customer"
    if storage.provider == "local":
        intent = intent.model_copy(
            update={
                "url": (f"{api_base_url()}/api/studio/materials/uploads/{intent.asset_id}/content")
            }
        )
    if is_customer:
        return JSONResponse(content=intent.model_dump(mode="json", exclude={"storage_key"}))
    return intent


@router.put("/uploads/{asset_id}/content", status_code=204)
async def put_local_material(
    asset_id: str,
    request: Request,
    conn: Database,
    actor: AuthenticatedUser,
    storage: MediaStorage,
) -> Response:
    if storage.provider != "local":
        raise HTTPException(status_code=404, detail={"code": "LOCAL_UPLOAD_UNAVAILABLE"})
    prepared = prepare_material_upload(conn, actor=actor, asset_id=asset_id)
    if prepared.upload_status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail={"code": "MATERIAL_UPLOAD_ALREADY_COMPLETED"},
        )
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > prepared.requested_size_bytes
    ):
        raise HTTPException(status_code=413, detail={"code": "PAYLOAD_TOO_LARGE"})
    content_type = request.headers.get("content-type", "application/octet-stream")
    if content_type != prepared.content_type:
        raise HTTPException(status_code=415, detail={"code": "CONTENT_TYPE_MISMATCH"})
    content = await request.body()
    if len(content) != prepared.requested_size_bytes:
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_SIZE_MISMATCH"})
    try:
        storage.put_object(prepared.storage_key, content, content_type=content_type)
    except StorageBackendUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "STORAGE_PROVIDER_UNAVAILABLE"},
        ) from exc
    return Response(status_code=204)


@router.post("/uploads/{asset_id}/complete", response_model=MaterialItem)
def complete_upload(
    asset_id: str,
    db: BusinessDbDep,
    storage: MediaStorage,
) -> MaterialItem:
    with db.write() as (conn, actor):
        prepared = prepare_material_upload(conn, actor=actor, asset_id=asset_id)
        if prepared.upload_status == "READY":
            return require_material(conn, actor=actor, material_id=f"asset:{asset_id}")
    try:
        probed = probe_material_upload(prepared, storage=storage)
        final_storage_key = material_final_storage_key(prepared, sha256=probed.sha256)
        stored = storage.put_object(
            final_storage_key,
            probed.content,
            content_type=prepared.content_type,
        )
        probed = replace(probed, storage_uri=stored.uri)
    except StorageBackendUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "STORAGE_PROVIDER_UNAVAILABLE"},
        ) from exc
    with db.write() as (conn, actor):
        result, committed_storage_uri = persist_material_upload(
            conn,
            actor=actor,
            probed=probed,
        )
    cleanup_keys = [prepared.storage_key]
    if stored.uri != committed_storage_uri:
        cleanup_keys.append(final_storage_key)
    for cleanup_key in dict.fromkeys(cleanup_keys):
        try:
            storage.delete_object(cleanup_key, actor_id=prepared.owner_user_id)
        except (OSError, StorageBackendUnavailable) as exc:
            logger.warning(
                "material upload object cleanup failed for asset %s: %s",
                prepared.asset_id,
                type(exc).__name__,
            )
    return result


@router.patch("/{material_id}", response_model=MaterialItem)
def patch_material(
    material_id: str,
    request: MaterialUpdateRequest,
    db: BusinessDbDep,
) -> MaterialItem:
    with db.write() as (conn, actor):
        return update_material(
            conn,
            actor=actor,
            material_id=material_id,
            request=request,
        )


@router.delete("/{material_id}", status_code=204)
def remove_material(material_id: str, db: BusinessDbDep) -> Response:
    with db.write() as (conn, actor):
        hide_material(conn, actor=actor, material_id=material_id)
    return Response(status_code=204)
