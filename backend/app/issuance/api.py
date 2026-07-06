"""Internal issuance / handover endpoints (mounted at /api/v1/issuances)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import (
    CurrentUser,
    get_issuance_service,
    require_permission,
    resolve_branch_scope,
)
from app.core.permissions import P
from app.issuance.schemas import (
    CancelBody,
    IssuanceCreate,
    IssuanceOut,
    IssuanceReturn,
)
from app.issuance.service import IssuanceService

router = APIRouter()


@router.post("", response_model=IssuanceOut, status_code=201)
async def create_issuance(
    payload: IssuanceCreate,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> IssuanceOut:
    return await svc.create(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("", response_model=list[IssuanceOut])
async def list_issuances(
    branch_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    open_only: bool = Query(default=False, alias="open"),
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> list[IssuanceOut]:
    return await svc.list_issuances(
        branch_ids=resolve_branch_scope(user, branch_id),
        status=status_filter, open_only=open_only, limit=limit,
    )


@router.get("/{issuance_id}", response_model=IssuanceOut)
async def get_issuance(
    issuance_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> IssuanceOut:
    return await svc.get(issuance_id)


@router.post("/{issuance_id}/issue", response_model=IssuanceOut)
async def issue_issuance(
    issuance_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> IssuanceOut:
    return await svc.issue(tenant_id=user.tenant_id, user_id=user.id, issuance_id=issuance_id)


@router.post("/{issuance_id}/return", response_model=IssuanceOut)
async def return_issuance(
    issuance_id: uuid.UUID,
    payload: IssuanceReturn,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_RECEIVE)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> IssuanceOut:
    return await svc.return_items(tenant_id=user.tenant_id, user_id=user.id, issuance_id=issuance_id, payload=payload)


@router.post("/{issuance_id}/cancel", response_model=IssuanceOut)
async def cancel_issuance(
    issuance_id: uuid.UUID,
    payload: CancelBody,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> IssuanceOut:
    return await svc.cancel(tenant_id=user.tenant_id, user_id=user.id, issuance_id=issuance_id, reason=payload.reason)


@router.get("/{issuance_id}/pdf")
async def issuance_pdf(
    issuance_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: IssuanceService = Depends(get_issuance_service),
) -> Response:
    from app.issuance.pdf import build_issuance_pdf

    iss = await svc.get(issuance_id)
    pdf = build_issuance_pdf(iss)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{iss.issuance_number}.pdf"'},
    )
