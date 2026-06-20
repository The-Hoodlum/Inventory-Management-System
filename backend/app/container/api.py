"""Container optimization endpoints.

Mounted at /api/v1/container. Planning is an analysis (read) operation — it reads
product carton dimensions and returns a load plan without persisting anything — so
it requires ``reorder.read``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_container_service, require_permission
from app.container.schemas import (
    ContainerOption,
    ContainerPlanRequest,
    ContainerPlanResponse,
    RecommendationPlanRequest,
)
from app.container.service import ContainerService
from app.core.permissions import P

router = APIRouter()


@router.get("/containers", response_model=list[ContainerOption])
async def list_containers(
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ContainerService = Depends(get_container_service),
) -> list[ContainerOption]:
    return svc.containers()


@router.post("/plan", response_model=ContainerPlanResponse)
async def plan_load(
    payload: ContainerPlanRequest,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ContainerService = Depends(get_container_service),
) -> ContainerPlanResponse:
    return await svc.plan(req=payload)


@router.post("/plan/from-recommendations", response_model=ContainerPlanResponse)
async def plan_from_recommendations(
    payload: RecommendationPlanRequest,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: ContainerService = Depends(get_container_service),
) -> ContainerPlanResponse:
    return await svc.plan_from_recommendations(req=payload)
