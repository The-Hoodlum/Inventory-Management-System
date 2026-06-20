"""Base repository: thin async helpers shared by concrete repositories.

Tenant isolation for business tables is enforced by PostgreSQL RLS (the request
sets ``app.current_tenant``), so read/update/delete queries here do NOT filter
by tenant_id. On INSERT, callers must set ``tenant_id`` to the current tenant so
the RLS ``WITH CHECK`` passes.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()  # populate server defaults (id, timestamps)
        return instance
