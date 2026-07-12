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
        # Capture the FX rate before the change so we can record who moved it (old -> new).
        before = await self.tenants.get(tenant_id)
        if before is None:
            raise NotFoundError("Tenant not found")
        old_fx = before.fx_rate
        old_vat = getattr(before, "vat_rate", None)

        tenant = await self.tenants.update(tenant_id, columns)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        await self.audit.add(
            tenant_id=tenant_id, user_id=actor_id, action="tenant.settings.update",
            entity_type="tenant", entity_id=tenant_id, changes={"fields": sorted(columns)},
        )
        # Dedicated, queryable audit for exchange-rate moves — the rate is financial and
        # gets snapshotted onto documents, so its change history matters on its own.
        if "fx_rate" in columns and tenant.fx_rate != old_fx:
            await self.audit.add(
                tenant_id=tenant_id, user_id=actor_id, action="tenant.fx_rate.update",
                entity_type="tenant", entity_id=tenant_id,
                changes={"old": str(old_fx), "new": str(tenant.fx_rate)},
            )
        # Same dedicated audit for the VAT rate — it is financial and snapshotted onto
        # documents, so its change history matters on its own.
        new_vat = getattr(tenant, "vat_rate", None)
        if "vat_rate" in columns and new_vat != old_vat:
            await self.audit.add(
                tenant_id=tenant_id, user_id=actor_id, action="tenant.vat_rate.update",
                entity_type="tenant", entity_id=tenant_id,
                changes={"old": str(old_vat), "new": str(new_vat)},
            )
        return TenantSettingsOut.from_tenant(tenant)
