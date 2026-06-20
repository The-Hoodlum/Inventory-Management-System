"""Intelligence endpoints.

Mounted at /api/v1/intelligence. Ingestion / manual entry are planning
operations (``reorder.run``); reads use ``reorder.read``. Dedicated
``intelligence.*`` permissions can be added later without changing handlers.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUser, get_intelligence_service, require_permission
from app.core.permissions import P
from app.intelligence.schemas import (
    IngestRequest,
    IngestResponse,
    IntelligenceDashboardResponse,
    ManualSignalRequest,
    PipelineImpactRequest,
    PipelineImpactResponse,
    SignalOut,
    SupplierScoreDetail,
    SupplierScoreOut,
    SupplierScoreRefreshResponse,
)
from app.intelligence.service import IntelligenceService
from app.schemas.common import Page

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/dashboard", response_model=IntelligenceDashboardResponse)
async def intelligence_dashboard(
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> IntelligenceDashboardResponse:
    return await svc.dashboard()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_intelligence(
    payload: IngestRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.REORDER_RUN)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> IngestResponse:
    return await svc.ingest(
        tenant_id=user.tenant_id, user_id=user.id,
        categories=payload.categories or None, ip=_ip(request),
    )


@router.post("/signals", response_model=SignalOut, status_code=201)
async def record_signal(
    payload: ManualSignalRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.REORDER_RUN)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> SignalOut:
    return await svc.record_manual(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )


@router.get("/signals", response_model=Page[SignalOut])
async def list_signals(
    category: str | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> Page[SignalOut]:
    items, total = await svc.list(
        category=category, scope_type=scope_type, page=page, page_size=page_size
    )
    return Page[SignalOut](
        items=[SignalOut.model_validate(s) for s in items],
        page=page, page_size=page_size, total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("/impact", response_model=PipelineImpactResponse)
async def pipeline_impact(
    payload: PipelineImpactRequest,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> PipelineImpactResponse:
    return await svc.pipeline_impact(
        base_daily_demand=payload.base_daily_demand, supplier_id=payload.supplier_id
    )


# ----------------------------- supplier scores ------------------------------ #
@router.post("/suppliers/refresh", response_model=SupplierScoreRefreshResponse)
async def refresh_supplier_scores(
    request: Request,
    user: CurrentUser = Depends(require_permission(P.REORDER_RUN)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> SupplierScoreRefreshResponse:
    return await svc.refresh_supplier_scores(
        tenant_id=user.tenant_id, user_id=user.id, ip=_ip(request)
    )


@router.get("/suppliers", response_model=list[SupplierScoreOut])
async def list_supplier_scores(
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> list[SupplierScoreOut]:
    scores = await svc.supplier_scores()
    return [SupplierScoreOut.model_validate(s) for s in scores]


@router.get("/suppliers/{supplier_id}", response_model=SupplierScoreDetail)
async def supplier_score_detail(
    supplier_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: IntelligenceService = Depends(get_intelligence_service),
) -> SupplierScoreDetail:
    return await svc.supplier_score_detail(supplier_id)
