"""HTTP endpoints for the reorder engine.

Two routers are exposed and mounted by the v1 aggregator:
  reorder_router         -> /api/v1/reorder              (run, recommendations)
  purchase_order_router  -> /api/v1/reorder/purchase-orders  (generate draft POs
                            from recommendations only)

Full purchase-order lifecycle, receiving, PDF, and email live in the dedicated
procurement module at /api/v1/purchase-orders.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUser, get_reorder_service, require_permission
from app.core.permissions import P
from app.reorder.schemas import (
    GeneratePurchaseOrdersRequest,
    GeneratePurchaseOrdersResponse,
    RecommendationOut,
    ReorderRunResponse,
    RunReorderRequest,
)
from app.reorder.service import ReorderService
from app.schemas.common import Page

reorder_router = APIRouter()
purchase_order_router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ------------------------------- reorder ------------------------------- #
@reorder_router.post("/run", response_model=ReorderRunResponse)
async def run_reorder(
    payload: RunReorderRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.REORDER_RUN)),
    svc: ReorderService = Depends(get_reorder_service),
) -> ReorderRunResponse:
    """Evaluate reorder needs across the selected scope and (optionally) persist
    actionable recommendations."""
    return await svc.run(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )


@reorder_router.get("/recommendations", response_model=Page[RecommendationOut])
async def list_recommendations(
    status_: str | None = Query(default=None, alias="status"),
    warehouse_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ReorderService = Depends(get_reorder_service),
) -> Page[RecommendationOut]:
    items, total = await svc.list_recommendations(
        status=status_,
        warehouse_id=warehouse_id,
        supplier_id=supplier_id,
        page=page,
        page_size=page_size,
    )
    return Page[RecommendationOut](
        items=[RecommendationOut.model_validate(r) for r in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


# --------------------------- purchase orders --------------------------- #
@purchase_order_router.post("", response_model=GeneratePurchaseOrdersResponse, status_code=201)
async def generate_purchase_orders(
    payload: GeneratePurchaseOrdersRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_CREATE)),
    svc: ReorderService = Depends(get_reorder_service),
) -> GeneratePurchaseOrdersResponse:
    """Generate draft purchase orders from selected recommendations, grouped by
    (supplier, warehouse). Recommendations without a supplier, or not in a
    convertible state, are skipped and reported back."""
    return await svc.create_purchase_orders(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )


# NOTE: listing and retrieving purchase orders now live in the dedicated
# procurement module (GET /api/v1/purchase-orders and /{po_id}). This router
# retains only draft-PO generation from reorder recommendations.
