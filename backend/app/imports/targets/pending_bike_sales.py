"""The "pending_bike_sales" import target: load motorcycles that were SOLD but not fully
paid, so they land on the Pending Payments (accounts-receivable) page with the right
outstanding balance and the right age.

This is a go-live reconstruction target. After a data reset, the serialized units are
re-imported (``motorcycle_units``); this then layers the *sale* on top for the bikes whose
buyers still owe money. Per row it, in ONE transaction for the whole batch:

  * matches an EXISTING sellable unit by chassis (never invents a bike),
  * finds-or-creates the buyer by name (phone/address filled on creation),
  * raises a bike invoice DATED to the original sale date (so AR aging is correct — the
    Pending Payments list and the motorcycle Sales Log both key off ``invoice.invoice_date``),
    priced directly in ZMW (VAT inclusive, extracted once), and
  * marks the unit sold + linked to that invoice through the real motorcycle lifecycle
    (``MotorcycleService.sell`` with notifications disabled — a historical import must never
    fire a WhatsApp alert or queue assembly).

The already-paid amount is recorded as the invoice's ``amount_paid`` (which is exactly what
drives the outstanding balance: ``grand_total_zmw - amount_paid - credit``). It does NOT
create receipt/payment rows and therefore posts NOTHING to the finance cash book — that money
was collected in the OLD system before go-live, so replaying it as new money-in would inflate
the opening cash position. The method the partial was paid by is kept on the invoice note for
the record. When staff later collect the remaining balance in the app, that IS new money and
posts to finance normally.

Atomic target (see app/imports/domain/atomic.py): validate up front, commit all-or-nothing,
no new references to confirm (a new buyer is created silently, like customer_delivery_notes).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports.domain.atomic import AtomicImporter, ImportPlan, RowInput, RowPlan
from app.imports.domain.fields import (
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_STANDARD,
    FieldKind,
    FieldSpec,
    RowResult,
)
from app.imports.domain.registry import register
from app.models import Customer, Invoice, MotorcycleUnit
from app.motorcycles.domain import lifecycle as L
from app.motorcycles.repository import MotorcycleRepository
from app.motorcycles.schemas import SellIn
from app.motorcycles.service import MotorcycleService
from app.repositories.audit_repo import AuditRepository
from app.sales.domain import pricing
from app.sales.domain.status import invoice_status_after_payment
from app.sales.repository import SalesRepository

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")
# Accepted spelling of how the partial was paid — informational only (kept on the note; no
# finance movement is posted for historical money). Aligned with the app's payment methods.
_METHODS = ("cash", "mobile_money", "bank_transfer", "card", "cheque", "credit")
_EPS = Decimal("0.0001")


def _parse_date(raw: Any) -> tuple[dt.date | None, bool]:
    """Return (date|None, ok). Empty -> (None, False): the sale date is required (aging)."""
    if isinstance(raw, dt.datetime):
        return raw.date(), True
    if isinstance(raw, dt.date):
        return raw, True
    s = ("" if raw is None else str(raw)).strip()
    if not s:
        return None, False
    s = s.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date(), True
        except ValueError:
            continue
    return None, False


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("date", "Sale Date", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("date", "sale date", "sold date", "invoice date", "purchase date")),
    FieldSpec("chassis_number", "Chassis Number", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("chassis", "chassis no", "chassis number", "vin", "frame number", "frame no")),
    FieldSpec("customer", "Customer", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("customer", "customer name", "buyer", "buyer name", "client", "sold to")),
    FieldSpec("price", "Price (ZMW)", required=True, kind=FieldKind.DECIMAL, levels=_ALL,
              aliases=("price", "amount", "total", "selling price", "sale price", "price zmw", "total price")),
    FieldSpec("amount_paid", "Amount Paid (ZMW)", kind=FieldKind.DECIMAL, levels=_ALL,
              aliases=("amount paid", "paid", "deposit", "paid amount", "amount received", "received")),
    FieldSpec("phone", "Phone", kind=FieldKind.STRING, levels=_STD,
              aliases=("phone", "phone number", "mobile", "contact", "telephone", "cell")),
    FieldSpec("address", "Address", kind=FieldKind.STRING, levels=_STD,
              aliases=("address", "customer address", "location", "residence")),
    FieldSpec("payment_method", "Payment Method", kind=FieldKind.ENUM, choices=_METHODS, levels=_STD,
              aliases=("payment method", "method", "paid by", "mode", "payment mode")),
    FieldSpec("invoice_number", "Invoice No.", kind=FieldKind.STRING, levels=_STD,
              aliases=("invoice", "invoice no", "invoice number", "inv no", "inv number", "bill no")),
)


class _Repo:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.s = session
        self.tenant_id = tenant_id

    async def find_unit(self, chassis: str) -> MotorcycleUnit | None:
        return await self.s.scalar(
            select(MotorcycleUnit).where(
                func.lower(MotorcycleUnit.chassis_number) == chassis.strip().lower()
            ).limit(1)
        )

    async def find_customer(self, name: str) -> Customer | None:
        return await self.s.scalar(
            select(Customer).where(func.lower(Customer.name) == name.strip().lower()).limit(1)
        )

    async def get_or_create_customer(self, name: str, phone: str | None, address: str | None) -> Customer:
        existing = await self.find_customer(name)
        if existing is not None:
            return existing
        code = await self.s.scalar(
            text("SELECT next_customer_number(CAST(:t AS uuid))"), {"t": str(self.tenant_id)}
        )
        customer = Customer(
            tenant_id=self.tenant_id, code=code, name=name.strip(),
            phone=(phone or None), notes=(f"Address: {address}" if address else None),
        )
        self.s.add(customer)
        await self.s.flush()
        return customer

    async def invoice_number_exists(self, number: str) -> bool:
        return await self.s.scalar(
            select(Invoice.id).where(
                func.lower(Invoice.invoice_number) == number.strip().lower()
            ).limit(1)
        ) is not None


class PendingBikeSalesImporter(AtomicImporter):
    key = "pending_bike_sales"
    label = "Pending bike sales (unpaid balances)"
    key_field = "chassis_number"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    async def plan(
        self, session: Any, *, tenant_id: Any, rows: list[RowInput], options: Any = None
    ) -> ImportPlan:
        repo = _Repo(session, tenant_id)
        plan = ImportPlan()
        seen_chassis: dict[str, int] = {}
        seen_invoice: dict[str, int] = {}

        for row_number, clean, field_errors in rows:
            errors = list(field_errors)

            when, ok = _parse_date(clean.get("date"))
            if not ok:
                errors.append("Sale Date is required and must be a valid date")

            chassis = clean.get("chassis_number")
            unit: MotorcycleUnit | None = None
            if chassis:
                cl = chassis.strip().lower()
                if cl in seen_chassis:
                    errors.append(f"Duplicate chassis '{chassis}' in file (row {seen_chassis[cl]})")
                else:
                    seen_chassis[cl] = row_number
                    unit = await repo.find_unit(chassis)
                    if unit is None:
                        errors.append(f"Chassis '{chassis}' is not on record — import the unit first")
                    elif unit.status not in L.SELLABLE_FROM:
                        errors.append(
                            f"Chassis '{chassis}' is {unit.status} and cannot be sold "
                            "(it may already be sold, or on hold)"
                        )

            price = clean.get("price")           # Decimal (>=0) or None
            paid = clean.get("amount_paid") or Decimal("0")
            if price is None or price <= 0:
                errors.append("Price (ZMW) is required and must be greater than zero")
            elif paid > price + _EPS:
                errors.append(
                    f"Amount Paid ({paid:g}) is more than the Price ({price:g})"
                )
            elif paid >= price - _EPS:
                # Fully paid is a completed sale, not a pending one — this target only builds
                # the accounts-receivable side, so a zero balance would never appear anywhere.
                errors.append(
                    "Amount Paid equals the Price — this bike is fully paid, not pending. "
                    "Record it as a normal sale instead."
                )

            inv_no = (clean.get("invoice_number") or "").strip()
            if inv_no:
                il = inv_no.lower()
                if il in seen_invoice:
                    errors.append(f"Duplicate invoice number '{inv_no}' in file (row {seen_invoice[il]})")
                else:
                    seen_invoice[il] = row_number
                    if await repo.invoice_number_exists(inv_no):
                        errors.append(f"Invoice number '{inv_no}' already exists")

            data = None
            if not errors and unit is not None:
                data = {
                    "unit_id": unit.id, "chassis_number": unit.chassis_number,
                    "branch_id": unit.branch_id, "when": when,
                    "customer": clean.get("customer").strip(),
                    "phone": (clean.get("phone") or "").strip() or None,
                    "address": (clean.get("address") or "").strip() or None,
                    "price": price, "paid": paid,
                    "method": clean.get("payment_method"),
                    "invoice_number": inv_no or None,
                }
            plan.rows.append(RowPlan(row_number=row_number, key=chassis, errors=errors, data=data))
        return plan

    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        repo = _Repo(session, tenant_id)
        srepo = SalesRepository(session)
        # notifications=None: a historical import must not push WhatsApp alerts or queue assembly.
        moto = MotorcycleService(MotorcycleRepository(session), AuditRepository(session), notifications=None)
        currency = await srepo.base_currency(tenant_id)
        vat_rate = await srepo.current_vat_rate(tenant_id)
        created = 0

        for rp in plan.rows:
            if rp.data is None:
                continue
            d = rp.data
            price: Decimal = d["price"]
            paid: Decimal = d["paid"]
            customer = await repo.get_or_create_customer(d["customer"], d["phone"], d["address"])

            # Bikes are priced directly in ZMW (fx_rate = 1); VAT is inclusive, extracted once.
            amt = pricing.line_amounts(1, price, 0, vat_rate * Decimal("100"), pricing.INCLUSIVE)
            note = f"Imported pending bike sale (job {job_id})"
            if d.get("method"):
                note += f"; {paid:g} paid via {d['method']}"
            invoice = Invoice(
                tenant_id=tenant_id,
                invoice_number=d["invoice_number"] or await srepo.number(tenant_id, "invoice", "INV"),
                invoice_date=d["when"],
                sales_order_id=None, delivery_note_id=None, customer_id=customer.id,
                branch_id=d["branch_id"], currency=currency, payment_terms="pos",
                status=invoice_status_after_payment(price, paid),
                subtotal=price, discount_total=Decimal("0"), net_total=amt["net"], tax_total=amt["vat"],
                grand_total=price, vat_rate=vat_rate, fx_rate=Decimal("1"), grand_total_zmw=price,
                amount_paid=paid, created_by=user_id,
            )
            session.add(invoice)
            await session.flush()

            # Mark the unit sold + linked through the real lifecycle. assembly_required=False:
            # the buyer already has the bike (this is a historical, already-delivered sale).
            await moto.sell(
                tenant_id=tenant_id, user_id=user_id, unit_id=d["unit_id"],
                payload=SellIn(invoice_id=invoice.id, customer_id=customer.id,
                               price_charged=float(price), note=note, assembly_required=False),
            )
            unit = await session.get(MotorcycleUnit, d["unit_id"])
            if unit is not None:
                unit.imported_historical = True
                unit.date_sold = d["when"]
            created += 1

        await session.flush()
        return created

    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("pending_bike_sales is an atomic target; use plan()/commit()")


register(PendingBikeSalesImporter())
