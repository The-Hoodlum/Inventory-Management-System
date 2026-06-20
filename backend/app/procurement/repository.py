"""Async data access for purchase orders, lines, and lifecycle events.

Tenant scoping is enforced by PostgreSQL RLS (the request sets
``app.current_tenant``). Mutating flows lock the PO and its lines with
``SELECT ... FOR UPDATE`` so concurrent approvals/receipts cannot race.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Product,
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    Supplier,
    Warehouse,
)


class ProcurementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------- numbering --------------------------- #
    async def next_po_number(self, tenant_id: uuid.UUID) -> str:
        res = await self.session.execute(
            text("SELECT next_po_number(CAST(:t AS uuid))"), {"t": str(tenant_id)}
        )
        return str(res.scalar_one())

    # ------------------------------ PO ------------------------------- #
    async def add_po(self, **fields: Any) -> PurchaseOrder:
        po = PurchaseOrder(**fields)
        self.session.add(po)
        await self.session.flush()
        return po

    async def get(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        return await self.session.get(PurchaseOrder, po_id)

    async def get_for_update(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        status: str | None = None,
        supplier_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[PurchaseOrder], int]:
        base = select(PurchaseOrder)
        if status:
            base = base.where(PurchaseOrder.status == status)
        if supplier_id:
            base = base.where(PurchaseOrder.supplier_id == supplier_id)
        if warehouse_id:
            base = base.where(PurchaseOrder.warehouse_id == warehouse_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = (
            base.order_by(PurchaseOrder.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total or 0)

    # ----------------------------- lines ----------------------------- #
    async def add_line(self, **fields: Any) -> PurchaseOrderLine:
        line = PurchaseOrderLine(**fields)
        self.session.add(line)
        await self.session.flush()
        return line

    async def lines_for(self, po_id: uuid.UUID) -> list[PurchaseOrderLine]:
        stmt = select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def lines_for_update(self, po_id: uuid.UUID) -> list[PurchaseOrderLine]:
        stmt = (
            select(PurchaseOrderLine)
            .where(PurchaseOrderLine.po_id == po_id)
            .with_for_update()
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_lines(self, po_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
        )

    # ----------------------------- events ---------------------------- #
    async def add_event(self, **fields: Any) -> PurchaseOrderEvent:
        event = PurchaseOrderEvent(**fields)
        self.session.add(event)
        await self.session.flush()
        return event

    async def events_for(self, po_id: uuid.UUID) -> list[PurchaseOrderEvent]:
        stmt = (
            select(PurchaseOrderEvent)
            .where(PurchaseOrderEvent.po_id == po_id)
            .order_by(PurchaseOrderEvent.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # -------------------------- lookups ------------------------------ #
    async def get_supplier(self, supplier_id: uuid.UUID) -> Supplier | None:
        return await self.session.get(Supplier, supplier_id)

    async def get_product(self, product_id: uuid.UUID) -> Product | None:
        return await self.session.get(Product, product_id)

    async def get_warehouse(self, warehouse_id: uuid.UUID) -> Warehouse | None:
        return await self.session.get(Warehouse, warehouse_id)
