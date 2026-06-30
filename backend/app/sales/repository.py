"""Data access for the Sales & Distribution engine: document numbering, locked
header reads, reservation holds/releases, lists, and enrichment maps.

Inventory is RESERVED against a sales-order line here (reserve on confirm, release on
cancel) by holding available stock without moving on-hand. The actual stock MOVEMENT —
deduct at delivery/POS, restock on return — is owned by ``InventoryService`` (the single
source of truth for qty_on_hand, the ledger, the audit trail, and demand); this
repository never mutates on-hand.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Branch,
    CreditNote,
    Customer,
    DeliveryNote,
    Inventory,
    Invoice,
    InvoiceLine,
    Product,
    Quotation,
    Return,
    SalesOrder,
    Warehouse,
)
from app.repositories.reservation_repo import ReservationRepository

SO_LINE_REF = "sales_order_line"


def _f(v) -> float:
    return float(v) if v is not None else 0.0


class SalesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reservations = ReservationRepository(session)

    # ------------------------------ numbering -------------------------- #
    async def number(self, tenant_id: uuid.UUID, doc_type: str, prefix: str) -> str:
        return await self.session.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(tenant_id), "d": doc_type, "p": prefix},
        )

    # --------------------------- locked header reads ------------------- #
    async def get_quote(self, qid: uuid.UUID, *, lock: bool = False) -> Quotation | None:
        stmt = select(Quotation).where(Quotation.id == qid)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_so(self, sid: uuid.UUID, *, lock: bool = False) -> SalesOrder | None:
        stmt = select(SalesOrder).where(SalesOrder.id == sid)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_delivery(self, did: uuid.UUID, *, lock: bool = False) -> DeliveryNote | None:
        stmt = select(DeliveryNote).where(DeliveryNote.id == did)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_invoice(self, iid: uuid.UUID, *, lock: bool = False) -> Invoice | None:
        stmt = select(Invoice).where(Invoice.id == iid)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_customer(self, cid: uuid.UUID) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.id == cid))

    async def get_return(self, rid: uuid.UUID) -> Return | None:
        return await self.session.scalar(select(Return).where(Return.id == rid))

    async def get_credit_note(self, cid: uuid.UUID, *, lock: bool = False) -> CreditNote | None:
        stmt = select(CreditNote).where(CreditNote.id == cid)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def invoice_line_index(self, invoice_id: uuid.UUID) -> dict[uuid.UUID, InvoiceLine]:
        """product_id -> invoice line, for pricing a credit note from the original sale."""
        res = await self.session.execute(
            select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)
        )
        return {ln.product_id: ln for ln in res.scalars().all()}

    async def list_returns(self, *, status: str | None, limit: int) -> list[Return]:
        stmt = select(Return)
        if status:
            stmt = stmt.where(Return.status == status)
        stmt = stmt.order_by(Return.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_credit_notes(self, *, status: str | None, limit: int) -> list[CreditNote]:
        stmt = select(CreditNote)
        if status:
            stmt = stmt.where(CreditNote.status == status)
        stmt = stmt.order_by(CreditNote.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def product_prices(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        if not ids:
            return {}
        res = await self.session.execute(
            select(Product.id, Product.selling_price).where(Product.id.in_(ids))
        )
        return {pid: Decimal(str(price)) for pid, price in res.all()}

    # ----------------------- inventory integration --------------------- #
    async def reserve_line(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID, location_id: uuid.UUID,
        qty: Decimal, so_line_id: uuid.UUID, user_id: uuid.UUID,
    ) -> str | None:
        """Hold `qty` at the selling location for a sales-order line. Returns an error
        string if AVAILABLE stock is insufficient, else None."""
        if qty <= 0:
            return None
        inv = await self.session.scalar(
            select(Inventory).where(
                Inventory.product_id == product_id, Inventory.warehouse_id == location_id
            ).with_for_update()
        )
        available = (inv.qty_on_hand - inv.qty_reserved - inv.qty_damaged) if inv else Decimal("0")
        if inv is None or available < qty:
            return (
                f"Insufficient available stock for product {product_id} "
                f"(available {_f(available):g}, need {_f(qty):g})"
            )
        await self.reservations.reserve(
            tenant_id=tenant_id, inv=inv, qty=qty, reference_id=so_line_id,
            user_id=user_id, reference_type=SO_LINE_REF,
        )
        return None

    async def release_reservation(
        self, *, tenant_id: uuid.UUID, so_line_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        res = await self.reservations.active_for(so_line_id, SO_LINE_REF)
        if res is None:
            return
        inv = await self.session.scalar(
            select(Inventory).where(
                Inventory.product_id == res.product_id, Inventory.warehouse_id == res.warehouse_id
            ).with_for_update()
        )
        if inv is not None:
            await self.reservations.release(tenant_id=tenant_id, inv=inv, reservation=res, user_id=user_id)

    # ------------------------------- lists ----------------------------- #
    async def list_quotes(self, *, status: str | None, customer_id: uuid.UUID | None, limit: int) -> list[Quotation]:
        return await self._list(Quotation, Quotation.created_at, status, customer_id, limit)

    async def list_sos(self, *, status: str | None, customer_id: uuid.UUID | None, limit: int) -> list[SalesOrder]:
        return await self._list(SalesOrder, SalesOrder.created_at, status, customer_id, limit)

    async def list_invoices(self, *, status: str | None, customer_id: uuid.UUID | None, limit: int) -> list[Invoice]:
        return await self._list(Invoice, Invoice.created_at, status, customer_id, limit)

    async def list_deliveries(self, *, status: str | None, limit: int) -> list[DeliveryNote]:
        stmt = select(DeliveryNote)
        if status:
            stmt = stmt.where(DeliveryNote.status == status)
        stmt = stmt.order_by(DeliveryNote.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _list(self, model, order_col, status, customer_id, limit) -> list:
        stmt = select(model)
        if status:
            stmt = stmt.where(model.status == status)
        if customer_id:
            stmt = stmt.where(model.customer_id == customer_id)
        stmt = stmt.order_by(order_col.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # ----------------------------- enrichment -------------------------- #
    async def product_index(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        res = await self.session.execute(
            select(Product.id, Product.sku, Product.name).where(Product.id.in_(ids))
        )
        return {pid: (sku, name) for pid, sku, name in res.all()}

    async def customer_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        res = await self.session.execute(select(Customer.id, Customer.name).where(Customer.id.in_(ids)))
        return {cid: name for cid, name in res.all()}

    async def branch_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        res = await self.session.execute(select(Branch.id, Branch.name).where(Branch.id.in_(ids)))
        return {bid: name for bid, name in res.all()}

    async def location_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        res = await self.session.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.id.in_(ids)))
        return {wid: name for wid, name in res.all()}

    async def quote_number(self, qid: uuid.UUID | None) -> str | None:
        if qid is None:
            return None
        return await self.session.scalar(select(Quotation.quote_number).where(Quotation.id == qid))

    async def so_number(self, sid: uuid.UUID | None) -> str | None:
        if sid is None:
            return None
        return await self.session.scalar(select(SalesOrder.so_number).where(SalesOrder.id == sid))
