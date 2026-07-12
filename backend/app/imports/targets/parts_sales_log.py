"""The "parts_sales_log" import target: load spare-part SALES HISTORY from a sheet (the
"Sales Log").

This is RECORD-ONLY history — it never writes stock. Current on-hand is set separately
from the inventory snapshot, so replaying these sales would double-count. Each row becomes
a ``parts_sales`` row; the Sales Log report unions those into parts revenue alongside live
``invoice_lines`` (the two sources are disjoint, so nothing is counted twice).

Atomic target (see app/imports/domain/atomic.py): the whole batch is validated up front
and committed in one transaction. There are no "new references" to confirm — an item code
not in the catalog is not an error; the row is still recorded (code + description kept) so
the sales log stays complete, with the product link left null.

Revenue basis: the sheet's "Total (ZMW)" is the ex-VAT line total, which is exactly the
basis the parts revenue stream uses. When it is present we take it verbatim (and back out
the effective fx rate); otherwise we compute qty x unit_price_usd x fx (default 20).
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
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
from app.models import PartsSale, Product

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)

# The spreadsheet prices parts in USD and shows ZMW at this rate; used only as a fallback
# when a row has no "Total (ZMW)" to read the effective rate from.
DEFAULT_FX = Decimal("20")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("date", "Date", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("date", "sale date", "sold date", "transaction date")),
    FieldSpec("item_code", "Item Code", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("item code", "code", "part no", "part number", "sku", "product code", "stock code")),
    FieldSpec("description", "Description", kind=FieldKind.STRING, levels=_STD,
              aliases=("description", "desc", "item", "product", "details")),
    FieldSpec("unit_price_usd", "Unit Price (USD)", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("unit price (usd)", "unit price", "price (usd)", "price", "unit cost")),
    FieldSpec("qty", "Qty", required=True, kind=FieldKind.DECIMAL, levels=_ALL,
              aliases=("qty", "quantity", "units", "qty sold", "number")),
    FieldSpec("total_zmw", "Total (ZMW)", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("total (zmw)", "total zmw", "total", "amount (zmw)", "amount", "line total")),
    FieldSpec("vat_zmw", "With VAT (ZMW)", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("with vat (zmw)", "vat (zmw)", "with vat", "incl vat", "total with vat")),
    FieldSpec("customer", "Customer", kind=FieldKind.STRING, levels=_STD,
              aliases=("customer", "customer name", "buyer", "client", "sold to")),
    FieldSpec("remarks", "Remarks", kind=FieldKind.STRING, levels=_STD,
              aliases=("remarks", "note", "notes", "comment", "reference")),
)


def _parse_date(raw: Any) -> tuple[dt.date | None, bool]:
    """Return (date|None, ok). Empty -> (None, False) since date is required here."""
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


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


class _Repo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def find_product(self, sku: str) -> Product | None:
        return await self.s.scalar(
            select(Product).where(func.lower(Product.sku) == sku.strip().lower()).limit(1)
        )


class PartsSalesLogImporter(AtomicImporter):
    key = "parts_sales_log"
    label = "Spare-part sales log (history)"
    key_field = "item_code"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    async def plan(
        self, session: Any, *, tenant_id: Any, rows: list[RowInput], options: Any = None
    ) -> ImportPlan:
        repo = _Repo(session)
        plan = ImportPlan()
        product_cache: dict[str, Product | None] = {}

        async def resolve(code: str) -> Product | None:
            cl = code.strip().lower()
            if cl not in product_cache:
                product_cache[cl] = await repo.find_product(code)
            return product_cache[cl]

        for row_number, clean, field_errors in rows:
            errors = list(field_errors)
            code = clean.get("item_code")
            sale_date, ok = _parse_date(clean.get("date"))
            if not ok:
                errors.append("Date is required and must be a valid date")

            qty = clean.get("qty")
            if qty is None:
                errors.append("Qty is required")
            elif qty <= 0:
                errors.append("Qty must be greater than zero")

            unit_price = clean.get("unit_price_usd")
            total_zmw = clean.get("total_zmw")
            vat_zmw = clean.get("vat_zmw")

            # Revenue basis: prefer the sheet's ex-VAT total; else compute from price x qty.
            fx = DEFAULT_FX
            revenue: Decimal | None = None
            if total_zmw is not None:
                revenue = total_zmw
                if unit_price and qty and unit_price > 0 and qty > 0:
                    fx = (total_zmw / (unit_price * qty)).quantize(Decimal("0.000001"))
            elif unit_price is not None and qty is not None:
                revenue = (unit_price * qty * fx)
            if revenue is None and not errors:
                errors.append("Need either a Total (ZMW) or a Unit Price (USD) to value the sale")

            data = None
            if not errors:
                product = await resolve(code)
                data = {
                    "product_id": product.id if product else None,
                    "item_code": code.strip(),
                    "description": (clean.get("description") or (product.name if product else None)),
                    "sale_date": sale_date, "qty": qty, "unit_price_usd": unit_price,
                    "fx_rate": fx, "revenue_zmw": revenue, "vat_zmw": vat_zmw,
                    "customer_name": (clean.get("customer") or None),
                    "remarks": (clean.get("remarks") or None),
                }
            plan.rows.append(RowPlan(row_number=row_number, key=code, errors=errors, data=data))
        return plan

    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        created = 0
        for rp in plan.rows:
            if rp.data is None:
                continue
            d = rp.data
            session.add(PartsSale(
                tenant_id=tenant_id, product_id=d["product_id"], item_code=d["item_code"],
                description=d["description"], sale_date=d["sale_date"], qty=d["qty"],
                unit_price_usd=d["unit_price_usd"], fx_rate=d["fx_rate"],
                revenue_zmw=d["revenue_zmw"], vat_zmw=d["vat_zmw"],
                customer_name=d["customer_name"], remarks=d["remarks"],
                imported_historical=True, import_job_id=job_id,
            ))
            created += 1
        await session.flush()
        return created

    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("parts_sales_log is an atomic target; use plan()/commit()")


register(PartsSalesLogImporter())
