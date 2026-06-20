"""Async data-access for the reorder & procurement module.

These repositories are the only place that touches the database. Tenant scoping
is handled by PostgreSQL RLS (the request sets ``app.current_tenant``), so queries
do not filter by tenant_id; inserts set tenant_id so the RLS WITH CHECK passes.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    ReorderRecommendation,
    SalesDaily,
    Supplier,
    SupplierProduct,
    Warehouse,
)
from app.models.inventory import Inventory

# PO statuses that still represent inbound (not-yet-received) stock.
OPEN_PO_STATUSES = ("draft", "pending_approval", "approved", "sent", "partially_received")


class ReorderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------- demand --------------------------- #
    async def demand_aggregates(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, start_date: dt.date
    ) -> tuple[Decimal, Decimal, int]:
        """Return (total_units, sum_of_squares, days_with_sales) over the window.

        Demand is first summed PER DAY across all sources (issue/import/pos/...),
        then totalled, so the sum-of-squares reflects whole-day demand and the
        variance the reorder engine derives stays correct regardless of how many
        sources contributed to a given day.
        """
        per_day = (
            select(
                SalesDaily.sale_date.label("d"),
                func.sum(SalesDaily.qty_sold).label("q"),
            )
            .where(
                SalesDaily.product_id == product_id,
                SalesDaily.warehouse_id == warehouse_id,
                SalesDaily.sale_date >= start_date,
            )
            .group_by(SalesDaily.sale_date)
            .subquery()
        )
        stmt = select(
            func.coalesce(func.sum(per_day.c.q), 0),
            func.coalesce(func.sum(per_day.c.q * per_day.c.q), 0),
            func.count(),
        )
        total, sum_sq, days = (await self.session.execute(stmt)).one()
        return Decimal(total), Decimal(sum_sq), int(days)

    # --------------------------- stock ---------------------------- #
    async def stock_position(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> tuple[Decimal, Decimal, Decimal]:
        stmt = select(
            Inventory.qty_on_hand, Inventory.qty_reserved, Inventory.qty_damaged
        ).where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return Decimal("0"), Decimal("0"), Decimal("0")
        return Decimal(row[0]), Decimal(row[1]), Decimal(row[2])

    async def on_order_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Decimal:
        stmt = (
            select(
                func.coalesce(
                    func.sum(PurchaseOrderLine.ordered_qty - PurchaseOrderLine.received_qty),
                    0,
                )
            )
            .select_from(PurchaseOrderLine)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id)
            .where(
                PurchaseOrderLine.product_id == product_id,
                PurchaseOrder.warehouse_id == warehouse_id,
                PurchaseOrder.status.in_(OPEN_PO_STATUSES),
            )
        )
        return Decimal(await self.session.scalar(stmt) or 0)

    # --------------------------- scope ---------------------------- #
    async def list_products(
        self,
        *,
        category_id: uuid.UUID | None = None,
        supplier_id: uuid.UUID | None = None,
    ) -> list[Product]:
        stmt = select(Product).where(
            Product.deleted_at.is_(None), Product.status == "active"
        )
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if supplier_id:
            stmt = stmt.where(Product.primary_supplier_id == supplier_id)
        stmt = stmt.order_by(Product.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_warehouses(
        self, *, warehouse_id: uuid.UUID | None = None
    ) -> list[Warehouse]:
        stmt = select(Warehouse)
        stmt = (
            stmt.where(Warehouse.id == warehouse_id)
            if warehouse_id
            else stmt.where(Warehouse.is_active.is_(True))
        )
        return list((await self.session.execute(stmt.order_by(Warehouse.code))).scalars().all())

    async def get_product(self, product_id: uuid.UUID) -> Product | None:
        return await self.session.get(Product, product_id)

    async def get_supplier(self, supplier_id: uuid.UUID) -> Supplier | None:
        return await self.session.get(Supplier, supplier_id)

    async def get_supplier_product(
        self, supplier_id: uuid.UUID, product_id: uuid.UUID
    ) -> SupplierProduct | None:
        stmt = select(SupplierProduct).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.product_id == product_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ----------------------- recommendations ---------------------- #
    async def save_recommendation(self, **fields: Any) -> ReorderRecommendation:
        rec = ReorderRecommendation(**fields)
        self.session.add(rec)
        await self.session.flush()
        return rec

    async def list_recommendations(
        self,
        *,
        status: str | None = None,
        warehouse_id: uuid.UUID | None = None,
        supplier_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ReorderRecommendation], int]:
        base = select(ReorderRecommendation)
        if status:
            base = base.where(ReorderRecommendation.status == status)
        if warehouse_id:
            base = base.where(ReorderRecommendation.warehouse_id == warehouse_id)
        if supplier_id:
            base = base.where(ReorderRecommendation.supplier_id == supplier_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = (
            base.order_by(ReorderRecommendation.generated_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total or 0)

    async def get_recommendations_by_ids(
        self, ids: list[uuid.UUID]
    ) -> list[ReorderRecommendation]:
        if not ids:
            return []
        stmt = select(ReorderRecommendation).where(ReorderRecommendation.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars().all())
