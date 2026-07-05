"""The "stock_reconciliation" import target: the RECONCILIATION GATE — the whole point of
a reconstruction. After opening balances (step 1) and the transaction replay (step 2), this
compares the system's COMPUTED current stock to the user's ACTUAL physical count and reports
the delta per product+location, so a reconstruction can be PROVEN correct before it is trusted.

This is an ATOMIC target (app/imports/domain/atomic.py) with a delta gate on top of the usual
all-or-nothing commit:
- ``plan`` matches product/warehouse (never created) and, for each, records computed (current
  on-hand) vs actual (the sheet's count) + the signed delta. A delta is NOT a row error — it
  is surfaced in the preview's reconciliation report.
- The service refuses to commit while any non-zero delta remains UNLESS the user sets
  ``accept_deltas`` (recorded). A clean run has all-zero deltas and commits a no-op.
- ``commit`` posts one correcting stock ADJUSTMENT (delta = actual - computed) per non-zero
  line through the inventory core, bringing the system to match the counted reality; zero
  deltas write nothing.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports.domain.atomic import AtomicImporter, ImportPlan, ReconLine, RowInput, RowPlan
from app.imports.domain.fields import (
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_STANDARD,
    FieldKind,
    FieldSpec,
    RowResult,
)
from app.imports.domain.registry import register
from app.models import Inventory, Product
from app.models.inventory import Branch, Warehouse
from app.repositories.audit_repo import AuditRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.warehouse_repo import WarehouseRepository
from app.schemas.inventory import AdjustStockRequest
from app.services.inventory_service import InventoryService

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)


def _norm(s: Any) -> str:
    return ("" if s is None else str(s)).strip().lower()


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("product", "Product", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("product", "item", "sku", "item code", "product code", "part number",
                       "part no", "code", "item name", "product name")),
    FieldSpec("warehouse", "Warehouse", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("warehouse", "warehouse name", "location", "store", "site", "warehouse code")),
    FieldSpec("branch", "Branch", kind=FieldKind.STRING, levels=_STD,
              aliases=("branch", "branch name", "outlet", "showroom")),
    FieldSpec("actual_qty", "Actual Count", required=True, kind=FieldKind.DECIMAL, levels=_ALL,
              aliases=("actual", "actual qty", "actual quantity", "actual count", "physical count",
                       "counted", "count", "on hand", "on-hand", "qty")),
)


class _Repo:
    """Read-only matchers over the request session (RLS scopes to tenant)."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def find_product(self, token: str) -> Product | None:
        t = token.strip().lower()
        by_sku = await self.s.scalar(select(Product).where(func.lower(Product.sku) == t).limit(1))
        return by_sku or await self.s.scalar(select(Product).where(func.lower(Product.name) == t).limit(1))

    async def find_warehouse(self, token: str) -> Warehouse | None:
        t = token.strip().lower()
        by_code = await self.s.scalar(select(Warehouse).where(func.lower(Warehouse.code) == t).limit(1))
        return by_code or await self.s.scalar(select(Warehouse).where(func.lower(Warehouse.name) == t).limit(1))

    async def current_on_hand(self, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Decimal:
        v = await self.s.scalar(
            select(Inventory.qty_on_hand).where(
                Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id
            ).limit(1)
        )
        return v if v is not None else Decimal("0")

    async def branch_name(self, branch_id: uuid.UUID | None) -> str | None:
        if branch_id is None:
            return None
        return await self.s.scalar(select(Branch.name).where(Branch.id == branch_id).limit(1))


class StockReconciliationImporter(AtomicImporter):
    key = "stock_reconciliation"
    label = "Reconciliation (reconstruction)"
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

            product = None
            raw_product = clean.get("product")
            if raw_product:
                pl = _norm(raw_product)
                if pl not in product_cache:
                    product_cache[pl] = await repo.find_product(raw_product)
                product = product_cache[pl]
                if product is None:
                    errors.append(f"Product '{raw_product}' not found - create it first")

            warehouse = None
            raw_warehouse = clean.get("warehouse")
            if raw_warehouse:
                wl = _norm(raw_warehouse)
                if wl not in warehouse_cache:
                    warehouse_cache[wl] = await repo.find_warehouse(raw_warehouse)
                warehouse = warehouse_cache[wl]
                if warehouse is None:
                    errors.append(f"Warehouse '{raw_warehouse}' not found - create it first")

            raw_branch = clean.get("branch")
            if raw_branch and warehouse is not None:
                actual_branch = await repo.branch_name(warehouse.branch_id)
                if _norm(actual_branch) != _norm(raw_branch):
                    errors.append(
                        f"Branch '{raw_branch}' does not match warehouse '{raw_warehouse}' "
                        f"(it belongs to '{actual_branch or '-'}')"
                    )

            actual = clean.get("actual_qty")
            if actual is None:
                errors.append("Actual Count is required")

            if product is not None and warehouse is not None:
                key = (product.id, warehouse.id)
                if key in seen:
                    errors.append(f"Duplicate count for this product + warehouse (row {seen[key]})")
                else:
                    seen[key] = row_number

            data = None
            if not errors:
                computed = await repo.current_on_hand(product.id, warehouse.id)
                actual_d = Decimal(str(actual))
                delta = actual_d - computed
                plan.reconciliation.append(ReconLine(
                    product=product.sku, warehouse=warehouse.name,
                    computed=computed, actual=actual_d, delta=delta,
                ))
                data = {"product_id": product.id, "warehouse_id": warehouse.id, "delta": delta}
            plan.rows.append(RowPlan(row_number=row_number, key=raw_product, errors=errors, data=data))

        return plan

    # ------------------------------ commit ----------------------------- #
    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        inventory = InventoryService(
            InventoryRepository(session), ProductRepository(session),
            WarehouseRepository(session), AuditRepository(session), ReservationRepository(session),
        )
        adjusted = 0
        for rp in plan.rows:
            if rp.data is None or rp.data["delta"] == 0:
                continue  # a clean line reconciles with nothing to write
            await inventory.adjust(
                tenant_id=tenant_id, user_id=user_id,
                req=AdjustStockRequest(
                    warehouse_id=rp.data["warehouse_id"], product_id=rp.data["product_id"],
                    delta=rp.data["delta"], reason="Reconstruction reconciliation (accepted)",
                ),
            )
            adjusted += 1
        await session.flush()
        return adjusted

    # Not used for atomic targets (kept to satisfy the base contract).
    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("stock_reconciliation is an atomic target; use plan()/commit()")


register(StockReconciliationImporter())
