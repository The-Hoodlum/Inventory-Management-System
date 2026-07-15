"""The "customer_delivery_notes" import target: load HISTORICAL customer delivery notes
(a bike handed to a customer) from a spreadsheet.

RECORD-ONLY history — like the sale itself, a customer SALE delivery is only proof of a
handover; it never moves stock (the sale already deducted / marked the unit sold). So each
row simply documents "this chassis was delivered to this customer on this date" by creating
a completed ``customer_deliveries`` row (mode=sale, status=delivered) with a single
motorcycle line. No stock, no sale, no invoice is fabricated.

Atomic target (see app/imports/domain/atomic.py): the whole batch is validated up front and
committed in one transaction. There are no "new references" to confirm.

Smart chassis matching: each row is matched to an EXISTING unit by chassis (trimmed,
case-insensitive). A chassis that is not on record is a row error — deliveries are recorded
against real units, never invented. The customer defaults to the unit's own buyer (the bike
is already sold to someone); a Customer column overrides / fills it in when the unit has
none. The source warehouse is taken from the unit (its warehouse, else a warehouse in its
branch). A bike that already has a delivery note is skipped as a duplicate.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
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
from app.models import (
    Customer,
    CustomerDelivery,
    CustomerDeliveryLine,
    Invoice,
    MotorcycleUnit,
    Warehouse,
)

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


def _norm(s: Any) -> str:
    return ("" if s is None else str(s)).strip().lower()


def _parse_date(raw: Any) -> tuple[dt.date | None, bool]:
    """Return (date|None, ok). Empty -> (None, False) since the delivery date is required."""
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
    FieldSpec("date", "Delivery Date", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("date", "delivery date", "delivered date", "dispatch date", "handover date")),
    FieldSpec("chassis_number", "Chassis Number", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("chassis", "chassis no", "chassis number", "vin", "frame number", "frame no")),
    FieldSpec("customer", "Customer", kind=FieldKind.STRING, levels=_ALL,
              aliases=("customer", "customer name", "buyer", "buyer name", "client", "delivered to", "sold to")),
    FieldSpec("invoice_number", "Invoice No.", kind=FieldKind.STRING, levels=_STD,
              aliases=("invoice", "invoice no", "invoice number", "inv no", "inv number", "bill no")),
    FieldSpec("received_by", "Received By", kind=FieldKind.STRING, levels=_STD,
              aliases=("received by", "receiver", "collected by", "signed by")),
    FieldSpec("remarks", "Remarks", kind=FieldKind.STRING, levels=_STD,
              aliases=("remarks", "note", "notes", "comment", "reference")),
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

    async def unit_has_delivery(self, unit_id: uuid.UUID) -> bool:
        return await self.s.scalar(
            select(CustomerDeliveryLine.id).where(CustomerDeliveryLine.unit_id == unit_id).limit(1)
        ) is not None

    async def warehouse_for_unit(self, unit: MotorcycleUnit) -> Warehouse | None:
        if unit.warehouse_id is not None:
            wh = await self.s.get(Warehouse, unit.warehouse_id)
            if wh is not None:
                return wh
        if unit.branch_id is not None:
            return await self.s.scalar(
                select(Warehouse).where(Warehouse.branch_id == unit.branch_id)
                .order_by(Warehouse.is_active.desc(), Warehouse.name).limit(1)
            )
        return None

    async def find_customer(self, name: str) -> Customer | None:
        return await self.s.scalar(
            select(Customer).where(func.lower(Customer.name) == name.strip().lower()).limit(1)
        )

    async def get_or_create_customer(self, name: str) -> Customer:
        existing = await self.find_customer(name)
        if existing is not None:
            return existing
        code = await self.s.scalar(
            text("SELECT next_customer_number(CAST(:t AS uuid))"), {"t": str(self.tenant_id)}
        )
        customer = Customer(tenant_id=self.tenant_id, code=code, name=name.strip())
        self.s.add(customer)
        await self.s.flush()
        return customer

    async def find_invoice(self, number: str) -> Invoice | None:
        return await self.s.scalar(
            select(Invoice).where(func.lower(Invoice.invoice_number) == number.strip().lower()).limit(1)
        )

    async def next_number(self) -> str:
        return await self.s.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(self.tenant_id), "d": "customer_delivery", "p": "CD"},
        )


class CustomerDeliveryNotesImporter(AtomicImporter):
    key = "customer_delivery_notes"
    label = "Customer delivery notes (history)"
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

        for row_number, clean, field_errors in rows:
            errors = list(field_errors)

            when, ok = _parse_date(clean.get("date"))
            if not ok:
                errors.append("Delivery Date is required and must be a valid date")

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
                    elif await repo.unit_has_delivery(unit.id):
                        errors.append(f"Chassis '{chassis}' already has a delivery note")

            # Customer: the unit's own buyer, else the sheet's Customer (created if new).
            customer_id: uuid.UUID | None = None
            sheet_customer = (clean.get("customer") or "").strip()
            if unit is not None:
                if unit.customer_id is not None:
                    customer_id = unit.customer_id
                elif not sheet_customer:
                    errors.append("No customer for this delivery — the bike has no buyer; add a Customer column")

            # Source warehouse (required on a customer delivery) — taken from the unit.
            warehouse_id: uuid.UUID | None = None
            branch_id: uuid.UUID | None = None
            if unit is not None:
                wh = await repo.warehouse_for_unit(unit)
                if wh is None:
                    errors.append(f"Chassis '{chassis}' has no branch/warehouse to deliver from")
                else:
                    warehouse_id = wh.id
                    branch_id = wh.branch_id

            # Invoice link: the sheet's invoice if named + found, else the unit's sold invoice.
            invoice_id: uuid.UUID | None = None
            inv_no = (clean.get("invoice_number") or "").strip()
            if inv_no:
                inv = await repo.find_invoice(inv_no)
                if inv is None:
                    errors.append(f"Invoice '{inv_no}' was not found")
                else:
                    invoice_id = inv.id
            elif unit is not None and unit.sold_ref is not None:
                invoice_id = unit.sold_ref

            data = None
            if not errors and unit is not None:
                data = {
                    "unit_id": unit.id, "chassis_number": unit.chassis_number,
                    "engine_number": unit.engine_number, "customer_id": customer_id,
                    "sheet_customer": sheet_customer or None, "warehouse_id": warehouse_id,
                    "branch_id": branch_id, "invoice_id": invoice_id, "when": when,
                    "received_by": (clean.get("received_by") or None),
                    "remarks": (clean.get("remarks") or None),
                }
            plan.rows.append(RowPlan(row_number=row_number, key=chassis, errors=errors, data=data))
        return plan

    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        repo = _Repo(session, tenant_id)
        created = 0
        for rp in plan.rows:
            if rp.data is None:
                continue
            d = rp.data
            customer_id = d["customer_id"]
            if customer_id is None and d.get("sheet_customer"):
                customer_id = (await repo.get_or_create_customer(d["sheet_customer"])).id

            when = d["when"]
            dispatched_at = dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC)
            audit = f"Imported delivery note (job {job_id})"
            cd = CustomerDelivery(
                tenant_id=tenant_id, delivery_number=await repo.next_number(),
                delivery_mode="sale", status="delivered", branch_id=d.get("branch_id"),
                from_warehouse_id=d["warehouse_id"], customer_id=customer_id,
                invoice_id=d.get("invoice_id"),
                remarks=f"{d['remarks']} — {audit}" if d.get("remarks") else audit,
                created_by=user_id, dispatched_by=user_id, dispatched_at=dispatched_at,
                received_by=d.get("received_by"), received_at=dispatched_at,
            )
            cd.lines = [CustomerDeliveryLine(
                tenant_id=tenant_id, line_kind="motorcycle", unit_id=d["unit_id"],
                chassis_number=d["chassis_number"], engine_number=d.get("engine_number"),
            )]
            session.add(cd)
            created += 1
        await session.flush()
        return created

    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("customer_delivery_notes is an atomic target; use plan()/commit()")


register(CustomerDeliveryNotesImporter())
