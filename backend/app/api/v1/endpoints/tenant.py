"""Tenant settings endpoints (mounted at /api/v1/tenant).

Read is available to any authenticated user (the UI and assistant need it); updates
require ``settings.manage``. This is the generic business-identity surface that keeps
the core platform industry-agnostic.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import (
    CurrentUser,
    get_current_user,
    get_tenant_service,
    require_permission,
)
from app.core.permissions import P
from app.schemas.tenant import TenantSettingsOut, TenantSettingsUpdate
from app.services.tenant_service import TenantSettingsService

router = APIRouter()


@router.get("/settings", response_model=TenantSettingsOut)
async def get_settings(
    user: CurrentUser = Depends(get_current_user),
    svc: TenantSettingsService = Depends(get_tenant_service),
) -> TenantSettingsOut:
    return await svc.get_settings(user.tenant_id)


@router.put("/settings", response_model=TenantSettingsOut)
async def update_settings(
    payload: TenantSettingsUpdate,
    user: CurrentUser = Depends(require_permission(P.SETTINGS_MANAGE)),
    svc: TenantSettingsService = Depends(get_tenant_service),
) -> TenantSettingsOut:
    return await svc.update_settings(user.tenant_id, payload, actor_id=user.id)
