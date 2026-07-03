"""Read-only aggregation queries for analytical reports (tenant-scoped by RLS).

Mirrors the dashboard repository's style: ORM ``select`` statements returning
lightweight tuples/dicts that the service layer composes into report schemas.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Branch,
    Inventory,
    Invoice,
    InvoiceLine,
    MotorcycleUnit,
    Product,
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    RequestHeader,
    RequestLine,
    StockMovement,
    Supplier,
    Warehouse,
)
from app.motorcycles.domain import lifecycle as L
from app.order_requests.domain import status as S
from app.sales.repository import _motorcycle_linked_invoice_ids


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

    # --------------------------- stock position --------------------------- #
    async def stock_position(
        self, *, branch_id: uuid.UUID | None, warehouse_id: uuid.UUID | None
    ) -> list[dict]:
        """Per (location, product): on_hand / reserved / available, joined to the branch.
        Optionally filtered to one branch and/or location."""
        stmt = (
            select(
                Warehouse.branch_id, Branch.name, Inventory.warehouse_id, Warehouse.name,
                Inventory.product_id, Product.sku, Product.name,
                Inventory.qty_on_hand, Inventory.qty_reserved, Inventory.qty_available,
            )
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .outerjoin(Branch, Branch.id == Warehouse.branch_id)
            .join(Product, Product.id == Inventory.product_id)
        )
        if warehouse_id is not None:
            stmt = stmt.where(Inventory.warehouse_id == warehouse_id)
        if branch_id is not None:
            stmt = stmt.where(Warehouse.branch_id == branch_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "branch_id": r[0], "branch_name": r[1], "location_id": r[2], "location_name": r[3],
                "product_id": r[4], "sku": r[5], "name": r[6],
                "on_hand": Decimal(r[7]), "reserved": Decimal(r[8]), "available": Decimal(r[9]),
            }
            for r in rows
        ]

    async def in_transit_by_location(
        self, *, branch_id: uuid.UUID | None, warehouse_id: uuid.UUID | None
    ) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
        """In-transit quantity inbound to each (destination location, product): stock that
        has been issued from a source but not yet received. Keyed (location_id, product_id)."""
        accounted = (
            func.coalesce(RequestLine.received_qty, 0)
            + func.coalesce(RequestLine.missing_qty, 0)
            + func.coalesce(RequestLine.damaged_qty, 0)
        )
        in_transit = func.sum(RequestLine.issued_qty - accounted)
        stmt = (
            select(RequestHeader.destination_branch_id, RequestLine.product_id, in_transit)
            .join(RequestLine, RequestLine.request_id == RequestHeader.id)
            .where(
                RequestHeader.destination_branch_id.is_not(None),
                RequestHeader.status.in_(tuple(S.IN_TRANSIT_STATES)),
            )
            .group_by(RequestHeader.destination_branch_id, RequestLine.product_id)
        )
        if warehouse_id is not None:
            stmt = stmt.where(RequestHeader.destination_branch_id == warehouse_id)
        rows = (await self.session.execute(stmt)).all()
        out: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
        for loc_id, prod_id, qty in rows:
            q = Decimal(qty or 0)
            if q != 0:
                out[(loc_id, prod_id)] = q
        return out

    async def locations_lookup(self) -> dict[uuid.UUID, tuple[uuid.UUID | None, str, str | None]]:
        """location_id -> (branch_id, location_name, branch_name)."""
        rows = (await self.session.execute(
            select(Warehouse.id, Warehouse.branch_id, Warehouse.name, Branch.name)
            .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        )).all()
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    # ---------------------------- sales log ------------------------------- #
    async def parts_sale_events(
        self, *, branch_id: uuid.UUID | None, date_from: dt.date | None, date_to: dt.date | None,
    ) -> list[tuple[dt.date, uuid.UUID | None, Decimal, Decimal]]:
        """Spare-part sale contributions: (sale_date, branch_id, units, revenue) from
        ``invoice_lines`` (every line is a fungible product). Excludes motorcycle-linked
        invoices so a serialized-unit sale is never counted as a part."""
        stmt = (
            select(Invoice.invoice_date, Invoice.branch_id, InvoiceLine.qty, InvoiceLine.line_total)
            .join(Invoice, InvoiceLine.invoice_id == Invoice.id)
            .where(Invoice.id.not_in(_motorcycle_linked_invoice_ids()))
        )
        if branch_id is not None:
            stmt = stmt.where(Invoice.branch_id == branch_id)
        if date_from is not None:
            stmt = stmt.where(Invoice.invoice_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Invoice.invoice_date <= date_to)
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], Decimal(r[2]), Decimal(r[3])) for r in rows]

    async def motorcycle_sale_events(
        self, *, branch_id: uuid.UUID | None, date_from: dt.date | None, date_to: dt.date | None,
    ) -> list[tuple[dt.date, uuid.UUID | None, Decimal, bool]]:
        """Motorcycle sale contributions: (sale_date, branch_id, revenue, historical) for
        every SOLD unit (``status`` in POST_SALE — covers live sales and imported
        historical ones). One unit == one sale. Revenue is ``price_charged`` (fallback
        ``selling_price``). Sale date is the linked invoice date, else the recorded
        ``date_sold``, else the unit's last-update date."""
        sale_date = func.coalesce(
            Invoice.invoice_date, MotorcycleUnit.date_sold, cast(MotorcycleUnit.updated_at, Date)
        )
        revenue = func.coalesce(MotorcycleUnit.price_charged, MotorcycleUnit.selling_price, 0)
        stmt = (
            select(sale_date, MotorcycleUnit.branch_id, revenue, MotorcycleUnit.imported_historical)
            .select_from(MotorcycleUnit)
            .outerjoin(Invoice, Invoice.id == MotorcycleUnit.sold_ref)
            .where(MotorcycleUnit.status.in_(tuple(L.POST_SALE)))
        )
        if branch_id is not None:
            stmt = stmt.where(MotorcycleUnit.branch_id == branch_id)
        if date_from is not None:
            stmt = stmt.where(sale_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(sale_date <= date_to)
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], Decimal(r[2]), bool(r[3])) for r in rows]

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
