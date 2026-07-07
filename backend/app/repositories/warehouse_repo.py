"""Warehouse repository: get, list, create, delete."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models import Warehouse
from app.repositories.base import BaseRepository


class WarehouseRepository(BaseRepository[Warehouse]):
    model = Warehouse

    async def get(self, warehouse_id: uuid.UUID) -> Warehouse | None:
        return await self.session.get(Warehouse, warehouse_id)

    async def get_by_code(self, code: str) -> Warehouse | None:
        res = await self.session.execute(
            select(Warehouse).where(Warehouse.code == code)
        )
        return res.scalar_one_or_none()

    async def ids_in_branches(self, branch_ids) -> set[uuid.UUID]:
        """Warehouse ids that belong to any of the given branches (for branch-scoped
        inventory reads). Empty ``branch_ids`` -> empty set."""
        ids = list(branch_ids)
        if not ids:
            return set()
        res = await self.session.execute(
            select(Warehouse.id).where(Warehouse.branch_id.in_(ids))
        )
        return {row[0] for row in res.all()}

    async def list(
        self,
        *,
        active_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Warehouse], int]:
        base = select(Warehouse)
        if active_only:
            base = base.where(Warehouse.is_active.is_(True))
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Warehouse.code)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)

    async def delete(self, warehouse: Warehouse) -> None:
        await self.session.delete(warehouse)
        await self.session.flush()
