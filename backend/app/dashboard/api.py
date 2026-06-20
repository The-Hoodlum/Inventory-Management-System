"""Dashboard API: read-only KPI metrics for the home screen."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_dashboard_service, require_permission
from app.core.permissions import P
from app.dashboard.schemas import DashboardMetrics
from app.dashboard.service import DashboardService

router = APIRouter()


@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    _: CurrentUser = Depends(require_permission(P.DASHBOARD_READ)),
    svc: DashboardService = Depends(get_dashboard_service),
) -> DashboardMetrics:
    return await svc.get_metrics()
