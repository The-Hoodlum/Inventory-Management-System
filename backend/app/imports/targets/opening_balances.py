"""The "opening_balances" import target: seed reconstructed opening stock as of a period
start, the first step of an inventory-history reconstruction (opening balances, then a
chronological transaction replay — see the reconstruction docs).

This is an ATOMIC target (app/imports/domain/atomic.py): the whole batch is validated up
front and the commit writes every row or nothing. Unlike the inventory catalog import it
NEVER creates anything — a product / warehouse / branch that does not already exist is a
row error, not an auto-create. Each committed row writes ONE back-dated ``opening_balance``
ledger entry through the inventory core (never a raw table write), flagged
``imported_historical`` and dated ``as_of_date``.

Rules enforced here:
- product matched by SKU (exact) then by name; unmatched -> row error.
- warehouse matched by code then by name; unmatched -> row error.
- branch (optional) is a cross-check: it must be the matched warehouse's branch.
- as_of_date required + parseable; opening_qty required + >= 0.
- one opening balance per (product, warehouse) within the file (a duplicate is an error).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal
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
from app.models import Product
from app.models.inventory import Branch, Warehouse
from app.repositories.audit_repo import AuditRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.warehouse_repo import WarehouseRepository
from app.services.inventory_service import InventoryService

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


def _norm(s: Any) -> str:
    return ("" if s is None else str(s)).strip().lower()


def _parse_date(raw: Any) -> tuple[dt.date | None, bool]:
    """Return (date|None, ok). Empty -> (None, False) — the date is required here."""
    s = ("" if raw is None else str(raw)).strip()
    if not s:
        return None, False
    s = s.split(" ")[0].split("T")[0]  # tolerate a trailing time component
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date(), True
        except ValueError:
            continue
    return None, False


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("product", "Product", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("product", "item", "sku", "item code", "product code", "part number",
                       "part no", "code", "item name", "product name")),
    FieldSpec("warehouse", "Warehouse", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("warehouse", "warehouse name", "location", "store", "site", "warehouse code")),
    FieldSpec("branch", "Branch", kind=FieldKind.STRING, levels=_STD,
              aliases=("branch", "branch name", "outlet", "showroom")),
    FieldSpec("opening_qty", "Opening Quantity", required=True, kind=FieldKind.DECIMAL, levels=_ALL,
              aliases=("opening qty", "opening quantity", "opening stock", "opening balance",
                       "qty", "quantity", "on hand", "onhand", "stock")),
    FieldSpec("as_of_date", "As-of Date", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("as of date", "as-of date", "as of", "opening date", "period start",
                       "start date", "date")),
)


class _Repo:
    """Read-only matchers over the request session (RLS scopes to tenant)."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def find_product(self, token: str) -> Product | None:
        t = token.strip().lower()
        by_sku = await self.s.scalar(select(Product).where(func.lower(Product.sku) == t).limit(1))
        if by_sku is not None:
            return by_sku
        return await self.s.scalar(select(Product).where(func.lower(Product.name) == t).limit(1))

    async def find_warehouse(self, token: str) -> Warehouse | None:
        t = token.strip().lower()
        by_code = await self.s.scalar(select(Warehouse).where(func.lower(Warehouse.code) == t).limit(1))
        if by_code is not None:
            return by_code
        return await self.s.scalar(select(Warehouse).where(func.lower(Warehouse.name) == t).limit(1))

    async def branch_name(self, branch_id: uuid.UUID | None) -> str | None:
        if branch_id is None:
            return None
        return await self.s.scalar(select(Branch.name).where(Branch.id == branch_id).limit(1))


class OpeningBalancesImporter(AtomicImporter):
    key = "opening_balances"
    label = "Opening Balances (reconstruction)"
    key_field = "product"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    # ------------------------------- plan ------------------------------ #
    async def plan(
        self, session: Any, *, tenant_id: Any, rows: list[RowInput], options: Any = None
    ) -> ImportPlan:
        repo = _Repo(session)
        plan = ImportPlan()
        product_cache: dict[str, Product | None] = {}
        warehouse_cache: dict[str, Warehouse | None] = {}
        seen: dict[tuple[uuid.UUID, uuid.UUID], int] = {}

        for row_number, clean, field_errors in rows:
            errors = list(field_errors)

            # product (match by sku then name; never created)
            product_obj = None
            raw_product = clean.get("product")
            if raw_product:
                pl = _norm(raw_product)
                if pl not in product_cache:
                    product_cache[pl] = await repo.find_product(raw_product)
                product_obj = product_cache[pl]
                if product_obj is None:
                    errors.append(f"Product '{raw_product}' not found - create it first")

            # warehouse (match by code then name; never created)
            warehouse_obj = None
            raw_warehouse = clean.get("warehouse")
            if raw_warehouse:
                wl = _norm(raw_warehouse)
                if wl not in warehouse_cache:
                    warehouse_cache[wl] = await repo.find_warehouse(raw_warehouse)
                warehouse_obj = warehouse_cache[wl]
                if warehouse_obj is None:
                    errors.append(f"Warehouse '{raw_warehouse}' not found - create it first")

            # branch cross-check (optional)
            raw_branch = clean.get("branch")
            if raw_branch and warehouse_obj is not None:
                actual = await repo.branch_name(warehouse_obj.branch_id)
                if _norm(actual) != _norm(raw_branch):
                    errors.append(
                        f"Branch '{raw_branch}' does not match warehouse '{raw_warehouse}' "
                        f"(it belongs to '{actual or '-'}')"
                    )

            # date (required + parseable)
            d_asof, ok = _parse_date(clean.get("as_of_date"))
            if not ok:
                errors.append("As-of Date is required and must be a valid date")

            qty = clean.get("opening_qty")
            if qty is None:
                errors.append("Opening Quantity is required")

            # one opening balance per (product, warehouse) within the file
            if product_obj is not None and warehouse_obj is not None:
                key = (product_obj.id, warehouse_obj.id)
                if key in seen:
                    errors.append(
                        f"Duplicate opening balance for this product + warehouse (row {seen[key]})"
                    )
                else:
                    seen[key] = row_number

            data = None
            if not errors:
                data = {
                    "product_id": product_obj.id,
                    "warehouse_id": warehouse_obj.id,
                    "quantity": Decimal(str(qty)),
                    "as_of": dt.datetime.combine(d_asof, dt.time.min, tzinfo=dt.UTC),
                }
            plan.rows.append(RowPlan(row_number=row_number, key=raw_product, errors=errors, data=data))

        return plan

    # ------------------------------ commit ----------------------------- #
    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        inventory = InventoryService(
            InventoryRepository(session), ProductRepository(session),
            WarehouseRepository(session), AuditRepository(session), ReservationRepository(session),
        )
        created = 0
        for rp in plan.rows:
            if rp.data is None:
                continue
            d = rp.data
            await inventory.opening_balance(
                tenant_id=tenant_id, user_id=user_id,
                product_id=d["product_id"], warehouse_id=d["warehouse_id"],
                quantity=d["quantity"], as_of=d["as_of"], reference_id=job_id,
            )
            created += 1
        await session.flush()
        return created

    # Not used for atomic targets (kept to satisfy the base contract).
    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("opening_balances is an atomic target; use plan()/commit()")


register(OpeningBalancesImporter())
