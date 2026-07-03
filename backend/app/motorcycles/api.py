"""Motorcycle module endpoints (mounted at /api/v1/motorcycles).

Reference catalog CRUD (models / variants / colours), the per-unit registry, and the
audited lifecycle actions (transition / reserve / sell / transfer). Permission-gated
via the existing RBAC dependencies; tenant/branch scoping is enforced by RLS.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, get_motorcycle_service, require_permission
from app.core.permissions import P
from app.motorcycles.schemas import (
    ColourCreate,
    ColourOut,
    ColourUpdate,
    MetricsOut,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ReserveIn,
    SellIn,
    TransferIn,
    TransitionIn,
    UnitCreate,
    UnitOut,
    UnitUpdate,
    VariantCreate,
    VariantOut,
    VariantUpdate,
)
from app.motorcycles.service import MotorcycleService
from app.schemas.common import Page

router = APIRouter()


def _page(items, total, page, page_size):
    return {
        "items": items, "page": page, "page_size": page_size, "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


# ============================ reference: models ========================= #
@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> ModelOut:
    return await svc.create_model(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/models", response_model=Page[ModelOut])
async def list_models(
    search: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> Page[ModelOut]:
    items, total = await svc.list_models(search=search, active_only=active_only, page=page, page_size=page_size)
    return Page[ModelOut](**_page(items, total, page, page_size))


@router.patch("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> ModelOut:
    return await svc.update_model(tenant_id=user.tenant_id, user_id=user.id, model_id=model_id, payload=payload)


# =========================== reference: variants ======================== #
@router.post("/variants", response_model=VariantOut, status_code=status.HTTP_201_CREATED)
async def create_variant(
    payload: VariantCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> VariantOut:
    return await svc.create_variant(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/variants", response_model=Page[VariantOut])
async def list_variants(
    model_id: uuid.UUID | None = Query(default=None),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> Page[VariantOut]:
    items, total = await svc.list_variants(model_id=model_id, active_only=active_only, page=page, page_size=page_size)
    return Page[VariantOut](**_page(items, total, page, page_size))


@router.patch("/variants/{variant_id}", response_model=VariantOut)
async def update_variant(
    variant_id: uuid.UUID,
    payload: VariantUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> VariantOut:
    return await svc.update_variant(tenant_id=user.tenant_id, user_id=user.id, variant_id=variant_id, payload=payload)


# ============================ reference: colours ======================== #
@router.post("/colours", response_model=ColourOut, status_code=status.HTTP_201_CREATED)
async def create_colour(
    payload: ColourCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> ColourOut:
    return await svc.create_colour(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/colours", response_model=Page[ColourOut])
async def list_colours(
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> Page[ColourOut]:
    items, total = await svc.list_colours(active_only=active_only, page=page, page_size=page_size)
    return Page[ColourOut](**_page(items, total, page, page_size))


@router.patch("/colours/{colour_id}", response_model=ColourOut)
async def update_colour(
    colour_id: uuid.UUID,
    payload: ColourUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> ColourOut:
    return await svc.update_colour(tenant_id=user.tenant_id, user_id=user.id, colour_id=colour_id, payload=payload)


# ================================ metrics =============================== #
@router.get("/metrics", response_model=MetricsOut)
async def metrics(
    branch_id: uuid.UUID | None = Query(default=None),
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> MetricsOut:
    return await svc.metrics(branch_id=branch_id)


# ================================= units ================================ #
@router.post("/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: UnitCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.create_unit(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/units", response_model=Page[UnitOut])
async def list_units(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    branch_id: uuid.UUID | None = Query(default=None),
    model_id: uuid.UUID | None = Query(default=None),
    variant_id: uuid.UUID | None = Query(default=None),
    colour_id: uuid.UUID | None = Query(default=None),
    sold: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> Page[UnitOut]:
    items, total = await svc.list_units(
        search=search, status=status_filter, branch_id=branch_id, model_id=model_id,
        variant_id=variant_id, colour_id=colour_id, sold=sold, page=page, page_size=page_size,
    )
    return Page[UnitOut](**_page(items, total, page, page_size))


@router.get("/units/{unit_id}", response_model=UnitOut)
async def get_unit(
    unit_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.get_unit(unit_id)


@router.patch("/units/{unit_id}", response_model=UnitOut)
async def update_unit(
    unit_id: uuid.UUID,
    payload: UnitUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.update_unit(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/units/{unit_id}/transition", response_model=UnitOut)
async def transition_unit(
    unit_id: uuid.UUID,
    payload: TransitionIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.transition(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/units/{unit_id}/reserve", response_model=UnitOut)
async def reserve_unit(
    unit_id: uuid.UUID,
    payload: ReserveIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.reserve(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/units/{unit_id}/sell", response_model=UnitOut)
async def sell_unit(
    unit_id: uuid.UUID,
    payload: SellIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.sell(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)


@router.post("/units/{unit_id}/transfer", response_model=UnitOut)
async def transfer_unit(
    unit_id: uuid.UUID,
    payload: TransferIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: MotorcycleService = Depends(get_motorcycle_service),
) -> UnitOut:
    return await svc.transfer(tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload)
