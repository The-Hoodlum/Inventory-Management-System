"""Data access for container planning (tenant-scoped by RLS)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ReorderRecommendation


class ContainerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_products(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Product]:
        """Return the requested products keyed by id (carton dims come from these)."""
        if not product_ids:
            return {}
        stmt = select(Product).where(Product.id.in_(product_ids))
        return {p.id: p for p in (await self.session.execute(stmt)).scalars().all()}

    async def load_recommendations(
        self, recommendation_ids: list[uuid.UUID]
    ) -> list[ReorderRecommendation]:
        """Load reorder recommendations by id (their quantities seed the load plan)."""
        if not recommendation_ids:
            return []
        stmt = select(ReorderRecommendation).where(
            ReorderRecommendation.id.in_(recommendation_ids)
        )
        return list((await self.session.execute(stmt)).scalars().all())
