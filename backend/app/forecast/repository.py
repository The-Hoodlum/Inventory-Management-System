"""Data access for stored demand forecasts (tenant-scoped by RLS)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DemandForecast, Product


class ForecastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, **fields: Any) -> DemandForecast:
        forecast = DemandForecast(**fields)
        self.session.add(forecast)
        await self.session.flush()
        return forecast

    async def get(self, forecast_id: uuid.UUID) -> DemandForecast | None:
        return await self.session.get(DemandForecast, forecast_id)

    async def list(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        method: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[DemandForecast], int]:
        base = select(DemandForecast)
        if product_id:
            base = base.where(DemandForecast.product_id == product_id)
        if warehouse_id:
            base = base.where(DemandForecast.warehouse_id == warehouse_id)
        if method:
            base = base.where(DemandForecast.method == method)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = (
            base.order_by(DemandForecast.generated_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total or 0)

    async def list_active_product_ids(self) -> list[uuid.UUID]:
        stmt = (
            select(Product.id)
            .where(Product.deleted_at.is_(None), Product.status == "active")
            .order_by(Product.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def product_supplier_map(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        """Map products to their primary supplier (for risk matching on forecasts)."""
        if not product_ids:
            return {}
        stmt = select(Product.id, Product.primary_supplier_id).where(Product.id.in_(product_ids))
        return {
            pid: sid
            for pid, sid in (await self.session.execute(stmt)).all()
            if sid is not None
        }

    async def latest_per_pair(self) -> list[DemandForecast]:
        """Most recent forecast for each (product, warehouse) — backs the summary."""
        stmt = (
            select(DemandForecast)
            .distinct(DemandForecast.product_id, DemandForecast.warehouse_id)
            .order_by(
                DemandForecast.product_id,
                DemandForecast.warehouse_id,
                DemandForecast.generated_at.desc(),
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_all(self) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(DemandForecast)) or 0)
