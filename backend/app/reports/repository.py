"""Read-only aggregation queries for analytical reports (tenant-scoped by RLS).

Mirrors the dashboard repository's style: ORM ``select`` statements returning
lightweight tuples/dicts that the service layer composes into report schemas.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Product,
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    StockMovement,
    Supplier,
    Warehouse,
)


class ReportsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------ lookups ------------------------------ #
    async def product_lookup(self) -> dict[uuid.UUID, tuple[str, str, Decimal]]:
        stmt = select(Product.id, Product.sku, Product.name, Product.cost_price).where(
            Product.deleted_at.is_(None)
        )
        rows = (await self.session.execute(stmt)).all()
        return {r[0]: (r[1], r[2], Decimal(r[3])) for r in rows}

    async def warehouse_lookup(self) -> dict[uuid.UUID, str]:
        rows = (await self.session.execute(select(Warehouse.id, Warehouse.name))).all()
        return {r[0]: r[1] for r in rows}

    # --------------------------- inventory aging -------------------------- #
    async def movements_for_aging(
        self, warehouse_id: uuid.UUID | None
    ) -> list[tuple[uuid.UUID, uuid.UUID, Decimal, dt.datetime]]:
        """Signed stock movements ordered for a per-(product, warehouse) FIFO
        replay. Positive rows are inbound layers; negative rows consume them."""
        stmt = select(
            StockMovement.product_id,
            StockMovement.warehouse_id,
            StockMovement.quantity,
            StockMovement.created_at,
        )
        if warehouse_id is not None:
            stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
        stmt = stmt.order_by(
            StockMovement.product_id,
            StockMovement.warehouse_id,
            StockMovement.created_at,
            StockMovement.id,
        )
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], Decimal(r[2]), r[3]) for r in rows]

    # ------------------------- supplier performance ----------------------- #
    async def suppliers_basic(self) -> list[tuple[uuid.UUID, str, int]]:
        stmt = select(
            Supplier.id, Supplier.name, Supplier.default_lead_time_days
        ).where(Supplier.deleted_at.is_(None))
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], int(r[2])) for r in rows]

    async def pos_for_perf(
        self, since: dt.datetime | None
    ) -> list[tuple[uuid.UUID, uuid.UUID, str, dt.date | None, dt.datetime]]:
        stmt = select(
            PurchaseOrder.id,
            PurchaseOrder.supplier_id,
            PurchaseOrder.status,
            PurchaseOrder.expected_date,
            PurchaseOrder.created_at,
        )
        if since is not None:
            stmt = stmt.where(PurchaseOrder.created_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], str(r[2]), r[3], r[4]) for r in rows]

    async def po_line_totals(self) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
        stmt = select(
            PurchaseOrderLine.po_id,
            func.coalesce(func.sum(PurchaseOrderLine.ordered_qty), 0),
            func.coalesce(func.sum(PurchaseOrderLine.received_qty), 0),
        ).group_by(PurchaseOrderLine.po_id)
        rows = (await self.session.execute(stmt)).all()
        return {r[0]: (Decimal(r[1]), Decimal(r[2])) for r in rows}

    async def po_event_timestamps(self) -> dict[uuid.UUID, dict[str, dt.datetime]]:
        """First time each PO entered the 'sent' and 'received' states."""
        stmt = (
            select(
                PurchaseOrderEvent.po_id,
                PurchaseOrderEvent.to_status,
                func.min(PurchaseOrderEvent.created_at),
            )
            .where(PurchaseOrderEvent.to_status.in_(("sent", "received")))
            .group_by(PurchaseOrderEvent.po_id, PurchaseOrderEvent.to_status)
        )
        out: dict[uuid.UUID, dict[str, dt.datetime]] = {}
        for po_id, to_status, ts in (await self.session.execute(stmt)).all():
            out.setdefault(po_id, {})[str(to_status)] = ts
        return out
