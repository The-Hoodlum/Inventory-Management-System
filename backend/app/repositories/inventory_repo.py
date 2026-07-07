"""Inventory repository: locked reads, row creation, ledger writes, listing."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Select, func, select, text
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

    async def record_demand(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        qty: Decimal,
        source: str,
    ) -> None:
        """Feed today's outbound demand into ``sales_daily`` (additive upsert).

        Used by demand-driven issues (sales delivery / POS) so the forecast and
        reorder engines see consumption. Idempotent within a day per source: repeat
        issues accumulate rather than overwrite.
        """
        await self.session.execute(
            text(
                "INSERT INTO sales_daily "
                "(tenant_id, product_id, warehouse_id, sale_date, qty_sold, source) "
                "VALUES (CAST(:t AS uuid), CAST(:p AS uuid), CAST(:w AS uuid), CURRENT_DATE, :q, :s) "
                "ON CONFLICT (product_id, warehouse_id, sale_date, source) "
                "DO UPDATE SET qty_sold = sales_daily.qty_sold + EXCLUDED.qty_sold"
            ),
            {"t": str(tenant_id), "p": str(product_id), "w": str(warehouse_id),
             "q": float(qty), "s": source},
        )
        await self.session.flush()

    # ----------------------------- reads ----------------------------- #
    async def list_inventory(
        self,
        *,
        warehouse_id: uuid.UUID | None = None,
        warehouse_ids: Sequence[uuid.UUID] | None = None,
        product_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Inventory], int]:
        base: Select = select(Inventory)
        if warehouse_id:
            base = base.where(Inventory.warehouse_id == warehouse_id)
        # Server-side branch scope: restrict to the caller's allowed warehouses. None = all.
        if warehouse_ids is not None:
            base = base.where(Inventory.warehouse_id.in_(list(warehouse_ids)))
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
        warehouse_ids: Sequence[uuid.UUID] | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[StockMovement], int]:
        base = select(StockMovement)
        if product_id:
            base = base.where(StockMovement.product_id == product_id)
        if warehouse_id:
            base = base.where(StockMovement.warehouse_id == warehouse_id)
        if warehouse_ids is not None:
            base = base.where(StockMovement.warehouse_id.in_(list(warehouse_ids)))
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
