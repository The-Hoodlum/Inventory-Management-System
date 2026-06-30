"""Branch endpoints: create, list, get, update, delete.

Mutations require ``warehouse.manage`` (branches are stock reference data managed
by the same operators as locations). Reads require ``inventory.read`` because
branches are reference data needed by anyone who can view stock or raise transfers.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.deps import CurrentUser, get_branch_service, require_permission
from app.core.permissions import P
from app.schemas.branch import BranchCreate, BranchOut, BranchUpdate
from app.schemas.common import Page
from app.services.branch_service import BranchService

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.WAREHOUSE_MANAGE)),
    svc: BranchService = Depends(get_branch_service),
) -> BranchOut:
    branch = await svc.create(tenant_id=user.tenant_id, user_id=user.id, data=payload, ip=_ip(request))
    return BranchOut.model_validate(branch)


@router.get("", response_model=Page[BranchOut])
async def list_branches(
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.INVENTORY_READ)),
    svc: BranchService = Depends(get_branch_service),
) -> Page[BranchOut]:
    items, total = await svc.list(active_only=active_only, page=page, page_size=page_size)
    return Page[BranchOut](
        items=[BranchOut.model_validate(b) for b in items],
        page=page, page_size=page_size, total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{branch_id}", response_model=BranchOut)
async def get_branch(
    branch_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.INVENTORY_READ)),
    svc: BranchService = Depends(get_branch_service),
) -> BranchOut:
    return BranchOut.model_validate(await svc.get(branch_id))


@router.patch("/{branch_id}", response_model=BranchOut)
async def update_branch(
    branch_id: uuid.UUID,
    payload: BranchUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.WAREHOUSE_MANAGE)),
    svc: BranchService = Depends(get_branch_service),
) -> BranchOut:
    branch = await svc.update(
        tenant_id=user.tenant_id, user_id=user.id, branch_id=branch_id, data=payload, ip=_ip(request)
    )
    return BranchOut.model_validate(branch)


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_branch(
    branch_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.WAREHOUSE_MANAGE)),
    svc: BranchService = Depends(get_branch_service),
) -> Response:
    await svc.delete(tenant_id=user.tenant_id, user_id=user.id, branch_id=branch_id, ip=_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
