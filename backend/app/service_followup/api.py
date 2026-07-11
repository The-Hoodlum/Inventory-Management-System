"""Service follow-up endpoints (mounted at /api/v1/service-followup).

The call-back list for sold bikes (next service due, usage-scaled), logging a service,
setting a bike's usage profile, and editing the per-model service schedule. Permission-
gated via the existing motorcycle RBAC (read to view, manage to log/set usage, config to
edit the schedule); tenant/branch scoping is enforced by RLS.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.deps import (
    CurrentUser,
    get_service_followup_service,
    require_permission,
    resolve_branch_scope,
)
from app.core.permissions import P
from app.service_followup.schemas import (
    FollowUpPage,
    FollowUpRow,
    ServicePlanIn,
    ServicePlanOut,
    ServicePlansOut,
    ServiceRecordCreate,
    ServiceRecordOut,
    UsageUpdate,
)
from app.service_followup.service import ServiceFollowUpService

router = APIRouter()


@router.get("", response_model=FollowUpPage)
async def list_followups(
    status_filter: str | None = Query(default=None, alias="status"),
    branch_id: uuid.UUID | None = Query(default=None),
    model_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> FollowUpPage:
    return await svc.list_followups(
        branch_ids=resolve_branch_scope(user, branch_id), model_id=model_id,
        search=search, status=status_filter, page=page, page_size=page_size,
    )


# --------------------------------- schedule -------------------------------- #
@router.get("/plans", response_model=ServicePlansOut)
async def list_plans(
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> ServicePlansOut:
    return await svc.list_plans()


@router.put("/plans", response_model=ServicePlanOut)
async def upsert_plan(
    payload: ServicePlanIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> ServicePlanOut:
    return await svc.upsert_plan(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_plan(
    plan_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> Response:
    await svc.delete_plan(tenant_id=user.tenant_id, user_id=user.id, plan_id=plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------ per-unit actions --------------------------- #
@router.get("/units/{unit_id}/records", response_model=list[ServiceRecordOut])
async def list_records(
    unit_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> list[ServiceRecordOut]:
    return await svc.list_records(unit_id)


@router.post("/units/{unit_id}/records", response_model=ServiceRecordOut,
             status_code=status.HTTP_201_CREATED)
async def log_service(
    unit_id: uuid.UUID,
    payload: ServiceRecordCreate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> ServiceRecordOut:
    return await svc.log_service(
        tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload
    )


@router.patch("/units/{unit_id}/usage", response_model=FollowUpRow)
async def set_usage(
    unit_id: uuid.UUID,
    payload: UsageUpdate,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: ServiceFollowUpService = Depends(get_service_followup_service),
) -> FollowUpRow:
    return await svc.set_usage(
        tenant_id=user.tenant_id, user_id=user.id, unit_id=unit_id, payload=payload
    )
