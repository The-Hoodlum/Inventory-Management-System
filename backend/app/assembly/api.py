"""Assembly Planner endpoints (mounted at /api/v1/assembly).

A deterministic recommendation of which bikes to assemble from current stock, plus the per
model/colour target tuning. Reuses the motorcycle permissions: motorcycle.read to view the
plan / targets, motorcycle.config to tune targets. Tenant/branch scoping via RLS +
resolve_branch_scope.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import (
    CurrentUser,
    get_assembly_service,
    require_permission,
    resolve_branch_scope,
)
from app.assembly.schemas import AssemblyPlanOut, AssemblyTargetIn, AssemblyTargetOut
from app.assembly.service import AssemblyPlannerService
from app.core.permissions import P

router = APIRouter()


@router.get("/plan", response_model=AssemblyPlanOut)
async def get_plan(
    branch_id: uuid.UUID | None = Query(default=None),
    model_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: AssemblyPlannerService = Depends(get_assembly_service),
) -> AssemblyPlanOut:
    return await svc.plan(branch_ids=resolve_branch_scope(user, branch_id), model_id=model_id)


@router.get("/targets", response_model=list[AssemblyTargetOut])
async def list_targets(
    _: CurrentUser = Depends(require_permission(P.MOTORCYCLE_READ)),
    svc: AssemblyPlannerService = Depends(get_assembly_service),
) -> list[AssemblyTargetOut]:
    return await svc.list_targets()


@router.put("/targets", response_model=AssemblyTargetOut, status_code=status.HTTP_200_OK)
async def upsert_target(
    payload: AssemblyTargetIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: AssemblyPlannerService = Depends(get_assembly_service),
) -> AssemblyTargetOut:
    return await svc.upsert_target(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_CONFIG)),
    svc: AssemblyPlannerService = Depends(get_assembly_service),
) -> None:
    await svc.delete_target(tenant_id=user.tenant_id, user_id=user.id, target_id=target_id)
