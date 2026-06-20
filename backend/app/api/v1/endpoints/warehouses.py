"""Warehouse endpoints: create, list, get, update, delete.

Mutations require ``warehouse.manage``. Reads require ``inventory.read`` because
warehouses are reference data needed by anyone who can view stock (the RBAC seed
has no separate ``warehouse.read`` permission).
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.deps import CurrentUser, get_warehouse_service, require_permission
from app.core.permissions import P
from app.schemas.common import Page
from app.schemas.warehouse import WarehouseCreate, WarehouseOut, WarehouseUpdate
from app.services.warehouse_service import WarehouseService

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: WarehouseCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.WAREHOUSE_MANAGE)),
    svc: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseOut:
    warehouse = await svc.create(
        tenant_id=user.tenant_id, user_id=user.id, data=payload, ip=_ip(request)
    )
    return WarehouseOut.model_validate(warehouse)


@router.get("", response_model=Page[WarehouseOut])
async def list_warehouses(
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.INVENTORY_READ)),
    svc: WarehouseService = Depends(get_warehouse_service),
) -> Page[WarehouseOut]:
    items, total = await svc.list(active_only=active_only, page=page, page_size=page_size)
    return Page[WarehouseOut](
        items=[WarehouseOut.model_validate(w) for w in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{warehouse_id}", response_model=WarehouseOut)
async def get_warehouse(
    warehouse_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.INVENTORY_READ)),
    svc: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseOut:
    return WarehouseOut.model_validate(await svc.get(warehouse_id))


@router.patch("/{warehouse_id}", response_model=WarehouseOut)
async def update_warehouse(
    warehouse_id: uuid.UUID,
    payload: WarehouseUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.WAREHOUSE_MANAGE)),
    svc: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseOut:
    warehouse = await svc.update(
        tenant_id=user.tenant_id,
        user_id=user.id,
        warehouse_id=warehouse_id,
        data=payload,
        ip=_ip(request),
    )
    return WarehouseOut.model_validate(warehouse)


@router.delete("/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_warehouse(
    warehouse_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.WAREHOUSE_MANAGE)),
    svc: WarehouseService = Depends(get_warehouse_service),
) -> Response:
    await svc.delete(
        tenant_id=user.tenant_id,
        user_id=user.id,
        warehouse_id=warehouse_id,
        ip=_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
