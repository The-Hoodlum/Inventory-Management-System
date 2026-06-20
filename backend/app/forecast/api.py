"""Forecast endpoints.

Mounted at /api/v1/forecast. Generating forecasts is a planning operation
(``reorder.run``); reads use ``reorder.read``. Dedicated ``forecast.*``
permissions can be introduced later without changing these handlers.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUser, get_forecast_service, require_permission
from app.core.permissions import P
from app.forecast.schemas import (
    DemandAnalyzeRequest,
    DemandPatternResponse,
    ForecastAccuracyResponse,
    ForecastOut,
    ForecastRunRequest,
    ForecastRunResponse,
    ForecastSummaryResponse,
    ProviderOut,
)
from app.forecast.service import ForecastService
from app.schemas.common import Page

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# Static paths declared before the parameterised "/{forecast_id}/..." route.
@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ForecastService = Depends(get_forecast_service),
) -> list[ProviderOut]:
    return svc.providers()


@router.get("/summary", response_model=ForecastSummaryResponse)
async def forecast_summary(
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ForecastService = Depends(get_forecast_service),
) -> ForecastSummaryResponse:
    return await svc.summary()


@router.post("/run", response_model=ForecastRunResponse)
async def run_forecast(
    payload: ForecastRunRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.REORDER_RUN)),
    svc: ForecastService = Depends(get_forecast_service),
) -> ForecastRunResponse:
    return await svc.run(
        tenant_id=user.tenant_id, user_id=user.id, req=payload, ip=_ip(request)
    )


@router.post("/analyze", response_model=DemandPatternResponse)
async def analyze_demand(
    payload: DemandAnalyzeRequest,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ForecastService = Depends(get_forecast_service),
) -> DemandPatternResponse:
    return await svc.analyze_demand(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        window_days=payload.window_days,
        as_of=payload.as_of,
    )


@router.get("", response_model=Page[ForecastOut])
async def list_forecasts(
    product_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    method: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ForecastService = Depends(get_forecast_service),
) -> Page[ForecastOut]:
    items, total = await svc.list(
        product_id=product_id, warehouse_id=warehouse_id, method=method,
        page=page, page_size=page_size,
    )
    return Page[ForecastOut](
        items=[ForecastOut.model_validate(f) for f in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{forecast_id}/accuracy", response_model=ForecastAccuracyResponse)
async def forecast_accuracy(
    forecast_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ForecastService = Depends(get_forecast_service),
) -> ForecastAccuracyResponse:
    return await svc.accuracy(forecast_id)
