"""Motorcycle (serialized-unit) registry endpoints (mounted at /api/v1/motorcycles).

Reads need ``motorcycle.read``; all writes (create/update/transition/reserve/sell/
transfer) need ``motorcycle.manage``. Every write goes through the audited state machine
in :class:`MotorcycleService`.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, get_motorcycle_service, require_permission
from app.core.permissions import P
from app.motorcycles.domain import lifecycle as L
from app.motorcycles.schemas import (
    MotorcycleUnitCreate,
    MotorcycleUnitOut,
    MotorcycleUnitUpdate,
    ReserveIn,
    SellIn,
    TransferIn,
    TransitionIn,
)
from app.motorcycles.service import MotorcycleService
from app.schemas.common import Page

router = APIRouter()


@router.get("/lifecycle", response_model=dict)
async def lifecycle_graph(_: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ))) -> dict:
    """The legal transition graph — lets the UI render quick actions without hard-coding it."""
    return {"statuses": sorted(L.STATUSES), "transitions": {s: L.allowed_next(s) for s in L.STATUSES}}


@router.get("", response_model=Page[MotorcycleUnitOut])
async def list_units(
    status_: str | None = Query(default=None, alias="status"),
    branch_id: uuid.UUID | None = None,
    model: str | None = None,
    colour: str | None = None,
    sold: bool | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> Page[MotorcycleUnitOut]:
    items, total = await svc.list_units(
        status=status_, branch_id=branch_id, model=model, colour=colour, sold=sold,
        search=search, page=page, page_size=page_size,
    )
    return Page[MotorcycleUnitOut](
        items=items, page=page, page_size=page_size, total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=MotorcycleUnitOut, status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: MotorcycleUnitCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.create_unit(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/{unit_id}", response_model=MotorcycleUnitOut)
async def get_unit(
    unit_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.get_unit(unit_id)


@router.patch("/{unit_id}", response_model=MotorcycleUnitOut)
async def update_unit(
    unit_id: uuid.UUID,
    payload: MotorcycleUnitUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.update_unit(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/{unit_id}/transition", response_model=MotorcycleUnitOut)
async def transition(
    unit_id: uuid.UUID,
    payload: TransitionIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.transition(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/{unit_id}/reserve", response_model=MotorcycleUnitOut)
async def reserve(
    unit_id: uuid.UUID,
    payload: ReserveIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.reserve(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/{unit_id}/sell", response_model=MotorcycleUnitOut)
async def sell(
    unit_id: uuid.UUID,
    payload: SellIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.sell(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/{unit_id}/transfer", response_model=MotorcycleUnitOut)
async def transfer(
    unit_id: uuid.UUID,
    payload: TransferIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MotorcycleUnitOut:
    return await svc.transfer(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)
