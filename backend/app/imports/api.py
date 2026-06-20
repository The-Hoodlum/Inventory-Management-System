"""Data-import endpoints (mounted at /api/v1/imports).

Phase 1: list targets, download templates, upload + auto-detect, validate preview,
and confirm (synchronous, batched, per-row isolated). History list + single-job
status are included so Phase 2/3 build on them. All require ``data.import``.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response

from app.api.v1.deps import CurrentUser, get_import_service, require_permission
from app.core.permissions import P
from app.imports.schemas import (
    ConfirmRequest,
    ImportJobListResponse,
    ImportJobOut,
    PreviewRequest,
    PreviewResponse,
    TargetOut,
    UploadResponse,
)
from app.imports.service import ImportService

router = APIRouter()


@router.get("/targets", response_model=list[TargetOut])
async def list_targets(
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> list[TargetOut]:
    return svc.targets()


@router.get("/targets/{key}", response_model=TargetOut)
async def get_target(
    key: str,
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> TargetOut:
    return svc.target(key)


@router.get("/targets/{key}/template")
async def download_template(
    key: str,
    level: str = Query(default="standard", pattern="^(basic|standard|advanced)$"),
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> Response:
    filename, content = svc.template(key, level)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{key}/upload", response_model=UploadResponse)
async def upload(
    key: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> UploadResponse:
    data = await file.read()
    return await svc.upload(
        key=key,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


@router.post("/{key}/{job_id}/preview", response_model=PreviewResponse)
async def preview(
    key: str,
    job_id: uuid.UUID,
    payload: PreviewRequest,
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> PreviewResponse:
    return await svc.preview(job_id=job_id, mapping=payload.mapping, options=payload.options)


@router.post("/{key}/{job_id}/confirm", response_model=ImportJobOut)
async def confirm(
    key: str,
    job_id: uuid.UUID,
    payload: ConfirmRequest,
    user: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> ImportJobOut:
    return await svc.confirm(
        job_id=job_id, mapping=payload.mapping, options=payload.options,
        tenant_id=user.tenant_id, user_id=user.id,
    )


@router.get("", response_model=ImportJobListResponse)
async def list_jobs(
    target_key: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> ImportJobListResponse:
    items, total = await svc.list_jobs(target_key=target_key, page=page, page_size=page_size)
    return ImportJobListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{job_id}/errors.csv")
async def download_errors(
    job_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> Response:
    filename, content = await svc.errors_csv(job_id)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{job_id}/rollback", response_model=ImportJobOut)
async def rollback(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> ImportJobOut:
    return await svc.rollback(job_id=job_id, tenant_id=user.tenant_id, user_id=user.id)


@router.post("/{job_id}/retry", response_model=ImportJobOut)
async def retry(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> ImportJobOut:
    return await svc.retry(job_id=job_id, tenant_id=user.tenant_id, user_id=user.id)


@router.post("/{job_id}/cancel", response_model=ImportJobOut)
async def cancel(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> ImportJobOut:
    return await svc.cancel(job_id=job_id, tenant_id=user.tenant_id, user_id=user.id)


@router.get("/{job_id}", response_model=ImportJobOut)
async def get_job(
    job_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DATA_IMPORT)),
    svc: ImportService = Depends(get_import_service),
) -> ImportJobOut:
    return await svc.get_job(job_id)
