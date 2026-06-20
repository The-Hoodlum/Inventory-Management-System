"""Inventory repository: locked reads, row creation, ledger writes, listing."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Inventory, StockMovement


class InventoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        stmt = select(Inventory).where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_for_update(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        """Row-level lock (SELECT ... FOR UPDATE) to serialize concurrent mutations."""
        stmt = (
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
            )
            .with_for_update()
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create(
        self,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
    ) -> Inventory:
        inv = Inventory(
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            qty_on_hand=Decimal("0"),
            qty_reserved=Decimal("0"),
            qty_damaged=Decimal("0"),
            version=0,
        )
        self.session.add(inv)
        await self.session.flush()
        return inv

    async def add_movement(self, **fields) -> StockMovement:
        mv = StockMovement(**fields)
        self.session.add(mv)
        await self.session.flush()
        return mv

    # ----------------------------- reads ----------------------------- #
    async def list_inventory(
        self,
        *,
        warehouse_id: uuid.UUID | None = None,
        product_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Inventory], int]:
        base: Select = select(Inventory)
        if warehouse_id:
            base = base.where(Inventory.warehouse_id == warehouse_id)
        if product_id:
            base = base.where(Inventory.product_id == product_id)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = base.limit(page_size).offset((page - 1) * page_size)
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)

    async def list_movements(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[StockMovement], int]:
        base = select(StockMovement)
        if product_id:
            base = base.where(StockMovement.product_id == product_id)
        if warehouse_id:
            base = base.where(StockMovement.warehouse_id == warehouse_id)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(StockMovement.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)
