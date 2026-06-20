"""Demand-pipeline endpoints.

Mounted at /api/v1/demand. The rollup is the automatic 'issue' demand channel
that feeds forecasting and the reorder engine. Gated by ``reorder.run`` — it is a
procurement-planning data operation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import CurrentUser, get_demand_service, require_permission
from app.core.permissions import P
from app.demand.schemas import RebuildDemandRequest, RebuildDemandResponse
from app.demand.service import DemandService

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/rebuild", response_model=RebuildDemandResponse)
async def rebuild_demand(
    payload: RebuildDemandRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.REORDER_RUN)),
    svc: DemandService = Depends(get_demand_service),
) -> RebuildDemandResponse:
    summary = await svc.rebuild_from_issues(
        tenant_id=user.tenant_id,
        user_id=user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        window_days=payload.window_days,
        warehouse_id=payload.warehouse_id,
        ip=_ip(request),
    )
    return RebuildDemandResponse(
        start_date=summary.start_date,
        end_date=summary.end_date,
        rows_written=summary.rows_written,
        warehouse_id=summary.warehouse_id,
    )
