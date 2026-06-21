"""Repository for the tenant registry row (business-identity settings)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self.session.scalar(select(Tenant).where(Tenant.id == tenant_id))

    async def update(self, tenant_id: uuid.UUID, columns: dict) -> Tenant | None:
        tenant = await self.get(tenant_id)
        if tenant is None:
            return None
        for col, value in columns.items():
            setattr(tenant, col, value)
        await self.session.flush()
        return tenant
