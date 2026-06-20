"""Aggregation queries for the dashboard (read-only, tenant-scoped by RLS)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Inventory, Product, PurchaseOrder, StockMovement, Supplier, Warehouse

_OPEN_PO_STATUSES = ("approved", "sent", "partially_received")


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_active_products(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Product)
            .where(Product.status == "active", Product.deleted_at.is_(None))
        )
        return int(await self.session.scalar(stmt) or 0)

    async def count_active_suppliers(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Supplier)
            .where(Supplier.status == "active", Supplier.deleted_at.is_(None))
        )
        return int(await self.session.scalar(stmt) or 0)

    async def count_active_warehouses(self) -> int:
        stmt = select(func.count()).select_from(Warehouse).where(Warehouse.is_active.is_(True))
        return int(await self.session.scalar(stmt) or 0)

    async def inventory_totals(self) -> tuple[Decimal, Decimal, Decimal]:
        stmt = select(
            func.coalesce(func.sum(Inventory.qty_on_hand), 0),
            func.coalesce(func.sum(Inventory.qty_available), 0),
            func.coalesce(func.sum(Inventory.qty_reserved), 0),
        )
        row = (await self.session.execute(stmt)).one()
        return Decimal(row[0]), Decimal(row[1]), Decimal(row[2])

    async def low_stock_count(self) -> int:
        """Inventory rows at or below the product's configured reorder point."""
        stmt = (
            select(func.count())
            .select_from(Inventory)
            .join(Product, Product.id == Inventory.product_id)
            .where(
                Product.reorder_point.is_not(None),
                Product.deleted_at.is_(None),
                Inventory.qty_available <= Product.reorder_point,
            )
        )
        return int(await self.session.scalar(stmt) or 0)

    async def po_status_counts(self) -> dict[str, int]:
        stmt = select(PurchaseOrder.status, func.count()).group_by(PurchaseOrder.status)
        rows = (await self.session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}

    async def open_purchase_orders(self) -> tuple[int, Decimal]:
        stmt = select(
            func.count(),
            func.coalesce(func.sum(PurchaseOrder.total), 0),
        ).where(PurchaseOrder.status.in_(_OPEN_PO_STATUSES))
        row = (await self.session.execute(stmt)).one()
        return int(row[0]), Decimal(row[1])

    async def receipts_since(self, since: dt.datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.movement_type == "receipt", StockMovement.created_at >= since)
        )
        return int(await self.session.scalar(stmt) or 0)
