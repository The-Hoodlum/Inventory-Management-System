"""Data access for the Sales & Distribution engine: document numbering, locked
header reads, reservation holds/releases, lists, and enrichment maps.

Inventory is RESERVED against a sales-order line here (reserve on confirm, release on
cancel) by holding available stock without moving on-hand. The actual stock MOVEMENT —
deduct at delivery/POS, restock on return — is owned by ``InventoryService`` (the single
source of truth for qty_on_hand, the ledger, the audit trail, and demand); this
repository never mutates on-hand.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Date, cast, column, func, select, table, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Branch,
    CreditNote,
    Customer,
    DeliveryNote,
    Inventory,
    Invoice,
    InvoiceLine,
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    Payment,
    PaymentAllocation,
    Product,
    Quotation,
    Return,
    SalesOrder,
    Tenant,
    User,
    Warehouse,
)
from app.repositories.reservation_repo import ReservationRepository

SO_LINE_REF = "sales_order_line"

# Invoices linked to a sold serialized motorcycle unit. A motorcycle's revenue lives
# on the unit (``price_charged``), never as an invoice line, so parts aggregations
# exclude these invoices as a belt-and-suspenders guard against double counting. Kept
# decoupled from the motorcycles ORM (raw table ref) to avoid a module import cycle.
_moto_units = table("motorcycle_units", column("sold_ref"))


def _motorcycle_linked_invoice_ids():
    return select(_moto_units.c.sold_ref).where(_moto_units.c.sold_ref.is_not(None))


def _f(v) -> float:
    return float(v) if v is not None else 0.0


class SalesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reservations = ReservationRepository(session)

    # ------------------------------ fx rate ---------------------------- #
    async def current_fx_rate(self, tenant_id: uuid.UUID) -> Decimal:
        """The tenant's CURRENT USD->billing rate, snapshotted onto a document at issue."""
        rate = await self.session.scalar(select(Tenant.fx_rate).where(Tenant.id == tenant_id))
        return Decimal(rate) if rate is not None else Decimal("1")

    async def base_currency(self, tenant_id: uuid.UUID) -> str:
        """The tenant's billing currency code (e.g. 'ZMW'). Used to label documents priced
        directly in that currency (like motorcycle sales)."""
        cur = await self.session.scalar(select(Tenant.base_currency).where(Tenant.id == tenant_id))
        return cur or "USD"

    async def current_vat_rate(self, tenant_id: uuid.UUID) -> Decimal:
        """The tenant's CURRENT VAT rate (fraction, 0.16 = 16%), snapshotted onto a
        document at creation so historical VAT never moves when the rate is changed."""
        rate = await self.session.scalar(select(Tenant.vat_rate).where(Tenant.id == tenant_id))
        return Decimal(rate) if rate is not None else Decimal("0")

    async def product_vat(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """product_id -> VAT treatment ('exclusive'/'inclusive'); default exclusive."""
        if not ids:
            return {}
        res = await self.session.execute(
            select(Product.id, Product.vat_treatment).where(Product.id.in_(ids))
        )
        return {pid: (t or "exclusive") for pid, t in res.all()}

    async def bike_unit_info(self, unit_id: uuid.UUID):
        """(chassis_number, model_name, selling_price, status) for a unit being quoted, or
        None. Raw table refs keep this decoupled from the motorcycles ORM."""
        u = table("motorcycle_units", column("id"), column("chassis_number"),
                  column("model_id"), column("selling_price"), column("status"))
        m = table("motorcycle_models", column("id"), column("name"))
        row = (await self.session.execute(
            select(u.c.chassis_number, m.c.name, func.coalesce(u.c.selling_price, 0), u.c.status)
            .select_from(u).outerjoin(m, m.c.id == u.c.model_id)
            .where(u.c.id == unit_id)
        )).first()
        return tuple(row) if row is not None else None

    async def bike_names(self, unit_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple]:
        """unit_id -> (chassis_number, model_name) for quotation bike-line output."""
        ids = [i for i in unit_ids if i]
        if not ids:
            return {}
        u = table("motorcycle_units", column("id"), column("chassis_number"), column("model_id"))
        m = table("motorcycle_models", column("id"), column("name"))
        rows = await self.session.execute(
            select(u.c.id, u.c.chassis_number, m.c.name)
            .select_from(u).outerjoin(m, m.c.id == u.c.model_id)
            .where(u.c.id.in_(ids))
        )
        return {r[0]: (r[1], r[2]) for r in rows}

    async def linked_bike(self, invoice_id: uuid.UUID):
        """The serialized bike sold on this invoice (chassis, model name, price), or None.
        Uses raw table refs to stay decoupled from the motorcycles ORM (see ``_moto_units``)."""
        u = table("motorcycle_units", column("sold_ref"), column("chassis_number"),
                  column("model_id"), column("price_charged"), column("selling_price"))
        m = table("motorcycle_models", column("id"), column("name"))
        row = (await self.session.execute(
            select(u.c.chassis_number, m.c.name,
                   func.coalesce(u.c.price_charged, u.c.selling_price, 0))
            .select_from(u).outerjoin(m, m.c.id == u.c.model_id)
            .where(u.c.sold_ref == invoice_id)
        )).first()
        return tuple(row) if row is not None else None

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

    # --------------------------- parts sales log ----------------------------- #
    async def list_parts_sales(
        self, *, branch_id: uuid.UUID | None = None, branch_ids: Sequence[uuid.UUID] | None = None,
        product_id: uuid.UUID | None = None,
        date_from: dt.date | None = None, date_to: dt.date | None = None, limit: int = 200,
    ) -> list:
        """Line-grain spare-part sales from invoices (the sale's money document), newest
        first. Excludes motorcycle-linked invoices (see ``_moto_units``). Rows are tuples
        aligned to ``SalesService._parts_sale_out``."""
        stmt = (
            select(
                InvoiceLine.id, Invoice.id, Invoice.invoice_number, Invoice.invoice_date,
                Invoice.status, InvoiceLine.product_id, Product.sku, Product.name,
                InvoiceLine.qty, InvoiceLine.unit_price, InvoiceLine.line_total,
                Invoice.branch_id, Branch.name, Invoice.customer_id, Customer.name,
                Invoice.created_at,
            )
            .join(Invoice, InvoiceLine.invoice_id == Invoice.id)
            .join(Product, InvoiceLine.product_id == Product.id)
            .join(Customer, Invoice.customer_id == Customer.id)
            .outerjoin(Branch, Invoice.branch_id == Branch.id)
            .where(Invoice.id.not_in(_motorcycle_linked_invoice_ids()))
        )
        if branch_id is not None:
            stmt = stmt.where(Invoice.branch_id == branch_id)
        if branch_ids is not None:
            stmt = stmt.where(Invoice.branch_id.in_(list(branch_ids)))
        if product_id is not None:
            stmt = stmt.where(InvoiceLine.product_id == product_id)
        if date_from is not None:
            stmt = stmt.where(Invoice.invoice_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Invoice.invoice_date <= date_to)
        stmt = stmt.order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).all())

    async def list_motorcycle_sales(
        self, *, branch_id: uuid.UUID | None = None, branch_ids: Sequence[uuid.UUID] | None = None,
        date_from: dt.date | None = None, date_to: dt.date | None = None, limit: int = 200,
    ) -> list:
        """Line-grain motorcycle sales history: one row per SOLD unit (live or imported
        historical), newest first, aligned to ``SalesService._moto_sale_out``. Sale date is
        the linked invoice's date, else date_sold, else the unit's last update."""
        sale_date = func.coalesce(
            Invoice.invoice_date, MotorcycleUnit.date_sold, cast(MotorcycleUnit.updated_at, Date)
        )
        revenue = func.coalesce(MotorcycleUnit.price_charged, MotorcycleUnit.selling_price, 0)
        stmt = (
            select(
                MotorcycleUnit.id, MotorcycleUnit.chassis_number, MotorcycleModel.name,
                MotorcycleColour.name, sale_date, Customer.name, revenue,
                Invoice.id, Invoice.invoice_number, MotorcycleUnit.imported_historical,
            )
            .select_from(MotorcycleUnit)
            .outerjoin(Invoice, Invoice.id == MotorcycleUnit.sold_ref)
            .outerjoin(Customer, Customer.id == MotorcycleUnit.customer_id)
            .outerjoin(MotorcycleModel, MotorcycleModel.id == MotorcycleUnit.model_id)
            .outerjoin(MotorcycleColour, MotorcycleColour.id == MotorcycleUnit.colour_id)
            .where(MotorcycleUnit.status == "sold")
        )
        if branch_id is not None:
            stmt = stmt.where(MotorcycleUnit.branch_id == branch_id)
        if branch_ids is not None:
            stmt = stmt.where(MotorcycleUnit.branch_id.in_(list(branch_ids)))
        if date_from is not None:
            stmt = stmt.where(sale_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(sale_date <= date_to)
        stmt = stmt.order_by(sale_date.desc()).limit(limit)
        return list((await self.session.execute(stmt)).all())

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

    async def customer_details(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        """Full customer details for documents: name / phone / tax number / a formatted
        address (the default address, else the first). Keyed by customer id."""
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = await self.session.scalars(select(Customer).where(Customer.id.in_(ids)))
        out: dict[uuid.UUID, dict] = {}
        for c in rows:
            addrs = list(c.addresses) if c.addresses else []
            chosen = next((a for a in addrs if a.is_default), addrs[0] if addrs else None)
            address = None
            if chosen is not None:
                parts = [chosen.line1, chosen.line2, chosen.city, chosen.region, chosen.country]
                address = ", ".join(p for p in parts if p) or None
            out[c.id] = {"name": c.name, "phone": c.phone,
                         "tax_number": c.tax_number, "address": address}
        return out

    async def invoice_payments(self, invoice_id: uuid.UUID) -> list[tuple]:
        """An invoice's payment lines (via allocations), newest first, with the name of
        the user who took each. Returns (Payment, received_by_name)."""
        stmt = (
            select(Payment, User.full_name)
            .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
            .outerjoin(User, User.id == Payment.received_by)
            .where(PaymentAllocation.invoice_id == invoice_id)
            .order_by(Payment.created_at)
        )
        rows = await self.session.execute(stmt)
        return [(p, name) for p, name in rows.all()]

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
