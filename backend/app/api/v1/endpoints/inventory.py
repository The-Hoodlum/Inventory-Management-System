"""Inventory endpoints: receive, issue, adjust, transfer, and reads.

Every mutating operation is audited inside the service layer (see
``InventoryService``); these handlers only translate HTTP <-> service calls.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.v1.deps import (
    CurrentUser,
    get_inventory_service,
    require_permission,
    resolve_warehouse_scope,
)
from app.core.permissions import P
from app.models import Inventory
from app.schemas.common import Page
from app.schemas.inventory import (
    AdjustStockRequest,
    InventoryOut,
    IssueStockRequest,
    MovementOut,
    ReceiveStockRequest,
    TransferStockRequest,
)
from app.services.inventory_service import InventoryService

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _inv_out(inv: Inventory) -> InventoryOut:
    """Build the response, computing available from components so the value is
    correct even for rows mutated earlier in the same transaction."""
    available = inv.qty_on_hand - inv.qty_reserved - inv.qty_damaged
    return InventoryOut(
        id=inv.id,
        product_id=inv.product_id,
        warehouse_id=inv.warehouse_id,
        qty_on_hand=inv.qty_on_hand,
        qty_reserved=inv.qty_reserved,
        qty_damaged=inv.qty_damaged,
        qty_available=available,
        version=inv.version,
    )


@router.post("/receive", response_model=list[InventoryOut], status_code=status.HTTP_201_CREATED)
async def receive_stock(
    payload: ReceiveStockRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.INVENTORY_RECEIVE)),
    svc: InventoryService = Depends(get_inventory_service),
) -> list[InventoryOut]:
    rows = await svc.receive(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )
    return [_inv_out(r) for r in rows]


@router.post("/issue", response_model=list[InventoryOut])
async def issue_stock(
    payload: IssueStockRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.INVENTORY_ISSUE)),
    svc: InventoryService = Depends(get_inventory_service),
) -> list[InventoryOut]:
    rows = await svc.issue(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )
    return [_inv_out(r) for r in rows]


@router.post("/adjust", response_model=InventoryOut)
async def adjust_stock(
    payload: AdjustStockRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.INVENTORY_ADJUST)),
    svc: InventoryService = Depends(get_inventory_service),
) -> InventoryOut:
    inv = await svc.adjust(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )
    return _inv_out(inv)


@router.post("/transfer", response_model=list[InventoryOut])
async def transfer_stock(
    payload: TransferStockRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.INVENTORY_TRANSFER)),
    svc: InventoryService = Depends(get_inventory_service),
) -> list[InventoryOut]:
    rows = await svc.transfer(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )
    return [_inv_out(r) for r in rows]


@router.get("", response_model=Page[InventoryOut])
async def list_inventory(
    warehouse_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_permission(P.INVENTORY_READ)),
    svc: InventoryService = Depends(get_inventory_service),
) -> Page[InventoryOut]:
    scope = await resolve_warehouse_scope(user, warehouse_id, svc.warehouses)
    items, total = await svc.list_inventory(
        warehouse_ids=scope, product_id=product_id, page=page, page_size=page_size
    )
    return Page[InventoryOut](
        items=[_inv_out(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/movements", response_model=Page[MovementOut])
async def list_movements(
    product_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_permission(P.INVENTORY_READ)),
    svc: InventoryService = Depends(get_inventory_service),
) -> Page[MovementOut]:
    scope = await resolve_warehouse_scope(user, warehouse_id, svc.warehouses)
    items, total = await svc.list_movements(
        product_id=product_id, warehouse_ids=scope, page=page, page_size=page_size
    )
    return Page[MovementOut](
        items=[MovementOut.model_validate(m) for m in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )
