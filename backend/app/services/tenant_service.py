"""Tenant business-identity settings service.

Reads/updates the generic, per-tenant configuration that makes the platform
industry-agnostic (brand, industry, currency, assistant name/prompt, feature flags).
No business logic is hard-coded here — this only persists tenant settings.
"""
from __future__ import annotations

import uuid

from app.core.exceptions import NotFoundError
from app.repositories.audit_repo import AuditRepository
from app.repositories.tenant_repo import TenantRepository
from app.schemas.tenant import TenantSettingsOut, TenantSettingsUpdate


class TenantSettingsService:
    def __init__(self, tenants: TenantRepository, audit: AuditRepository) -> None:
        self.tenants = tenants
        self.audit = audit

    async def get_settings(self, tenant_id: uuid.UUID) -> TenantSettingsOut:
        tenant = await self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        return TenantSettingsOut.from_tenant(tenant)

    async def update_settings(
        self, tenant_id: uuid.UUID, payload: TenantSettingsUpdate, *, actor_id: uuid.UUID
    ) -> TenantSettingsOut:
        columns = payload.to_columns()
        tenant = await self.tenants.update(tenant_id, columns)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        await self.audit.add(
            tenant_id=tenant_id, user_id=actor_id, action="tenant.settings.update",
            entity_type="tenant", entity_id=tenant_id, changes={"fields": sorted(columns)},
        )
        return TenantSettingsOut.from_tenant(tenant)
