"""Customer Handover endpoints (mounted at /api/v1/handovers).

Reads are gated on ``motorcycle.read`` and writes on ``motorcycle.manage`` — the same
roles that sell and drive the lifecycle of a bike also record its handover, so no new RBAC
surface is introduced. Branch scope is enforced server-side via ``resolve_branch_scope``.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import (
    CurrentUser,
    get_handover_service,
    require_permission,
    resolve_branch_scope,
)
from app.core.permissions import P
from app.customer_handovers.schemas import (
    HandoverComplete,
    HandoverCreate,
    HandoverLookupOut,
    HandoverOut,
    HandoverUpdate,
)
from app.customer_handovers.service import CustomerHandoverService

router = APIRouter()


def _scope(user: CurrentUser, branch_id: uuid.UUID | None) -> frozenset[uuid.UUID] | None:
    ids = resolve_branch_scope(user, branch_id)
    return frozenset(ids) if ids is not None else None


@router.get("/lookup", response_model=HandoverLookupOut)
async def lookup_by_chassis(
    chassis: str = Query(min_length=1),
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> HandoverLookupOut:
    return await svc.lookup_by_chassis(
        tenant_id=user.tenant_id, chassis=chassis, allowed_branch_ids=_scope(user, None)
    )


@router.post("", response_model=HandoverOut, status_code=201)
async def create_handover(
    payload: HandoverCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> HandoverOut:
    return await svc.create(
        tenant_id=user.tenant_id, user_id=user.id, payload=payload,
        allowed_branch_ids=_scope(user, None),
    )


@router.get("", response_model=list[HandoverOut])
async def list_handovers(
    branch_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> list[HandoverOut]:
    return await svc.list_handovers(
        branch_ids=_scope(user, branch_id), status=status_filter,
        date_from=date_from, date_to=date_to, search=search, limit=limit,
    )


@router.get("/{handover_id}", response_model=HandoverOut)
async def get_handover(
    handover_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> HandoverOut:
    return await svc.get(handover_id, allowed_branch_ids=_scope(user, None))


@router.patch("/{handover_id}", response_model=HandoverOut)
async def update_handover(
    handover_id: uuid.UUID,
    payload: HandoverUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> HandoverOut:
    return await svc.update(
        tenant_id=user.tenant_id, user_id=user.id, handover_id=handover_id,
        payload=payload, allowed_branch_ids=_scope(user, None),
    )


@router.post("/{handover_id}/complete", response_model=HandoverOut)
async def complete_handover(
    handover_id: uuid.UUID,
    payload: HandoverComplete | None = None,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> HandoverOut:
    return await svc.complete(
        tenant_id=user.tenant_id, user_id=user.id, handover_id=handover_id,
        payload=payload, allowed_branch_ids=_scope(user, None),
    )


@router.get("/{handover_id}/pdf")
async def handover_pdf(
    handover_id: uuid.UUID,
    copy: str = Query(default="both", pattern="^(customer|internal|both)$"),
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: CustomerHandoverService = Depends(get_handover_service),
) -> Response:
    from app.customer_handovers.pdf import build_handover_pdf

    h = await svc.get(handover_id, allowed_branch_ids=_scope(user, None))
    pdf = build_handover_pdf(h, copy=copy)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{h.handover_no}.pdf"'},
    )
