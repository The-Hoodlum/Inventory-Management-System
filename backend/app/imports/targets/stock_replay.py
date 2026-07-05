"""The "stock_replay" import target: replay a period's stock movements — across mixed
TYPES — in strict chronological order through the real inventory engine, the second step
of an inventory-history reconstruction (opening balances first, then this replay).

This is an ATOMIC target (app/imports/domain/atomic.py): the whole file is validated up
front and the commit writes every movement or nothing. Every row is one movement of a
declared TYPE, and the direction is fixed by the type (never a free add/deduct toggle):

    SALE              -> InventoryService.issue     (on_hand down)
    RECEIPT/PURCHASE  -> InventoryService.receive   (on_hand up)
    RETURN            -> InventoryService.receive    (customer return; on_hand up)
    ADJUSTMENT        -> InventoryService.adjust     (signed delta)
    TRANSFER          -> InventoryService.transfer   (source -> destination)

The CRITICAL rule: ALL rows are merged into ONE timeline and processed strictly in
chronological order (ties broken deterministically by file row order), each through the
matching core method — same single write path, same ledger, marked ``imported_historical``
and dated ``occurred_at`` = the row's timestamp.

Validation before replay (in ``plan``): referenced product/warehouse exist (never created);
type + quantity + timestamp valid; no row predates that product+warehouse's reconstructed
opening balance. A chronological DRY-RUN then catches any movement that would drive stock
negative mid-replay (a missing receipt or out-of-order data) and STOPS on the first one,
reporting the exact row + timestamp — never silently allowed.
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
from app.models import Inventory, Product, StockMovement
from app.models.inventory import Warehouse
from app.repositories.audit_repo import AuditRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.warehouse_repo import WarehouseRepository
from app.schemas.inventory import (
    AdjustStockRequest,
    IssueLine,
    IssueStockRequest,
    ReceiptLine,
    ReceiveStockRequest,
    TransferStockRequest,
)
from app.services.inventory_service import InventoryService

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)

# Canonical movement kinds and how a sheet value maps to one (case-insensitive).
KIND_SALE, KIND_RECEIPT, KIND_RETURN, KIND_ADJUSTMENT, KIND_TRANSFER = (
    "sale", "receipt", "return", "adjustment", "transfer",
)
_TYPE_ALIASES: dict[str, str] = {
    "sale": KIND_SALE, "sold": KIND_SALE, "issue": KIND_SALE, "out": KIND_SALE,
    "receipt": KIND_RECEIPT, "purchase": KIND_RECEIPT, "grn": KIND_RECEIPT,
    "receive": KIND_RECEIPT, "in": KIND_RECEIPT, "po": KIND_RECEIPT,
    "return": KIND_RETURN, "sales return": KIND_RETURN, "customer return": KIND_RETURN,
    "adjustment": KIND_ADJUSTMENT, "adjust": KIND_ADJUSTMENT, "stock adjustment": KIND_ADJUSTMENT,
    "correction": KIND_ADJUSTMENT,
    "transfer": KIND_TRANSFER, "move": KIND_TRANSFER, "transfer out": KIND_TRANSFER,
}
_TRANSFER_KINDS = frozenset({KIND_TRANSFER})
_INFLOW = frozenset({KIND_RECEIPT, KIND_RETURN})

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y",
)


def _norm(s: Any) -> str:
    return ("" if s is None else str(s)).strip().lower()


def normalize_type(raw: Any) -> str | None:
    """Map a sheet type value to one of the five canonical kinds, or None if unknown."""
    return _TYPE_ALIASES.get(_norm(raw))


def parse_timestamp(raw: Any) -> tuple[dt.datetime | None, bool]:
    """Return (datetime|None, ok). Empty/garbage -> (None, False) — required here.
    A date-only value is anchored at midnight UTC; any parsed value is tz-aware UTC."""
    s = ("" if raw is None else str(raw)).strip()
    if not s:
        return None, False
    for fmt in _TS_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.UTC), True
        except ValueError:
            continue
    return None, False


def sort_key(entry: dict) -> tuple[dt.datetime, int]:
    """Strict chronological order; ties broken deterministically by file row number."""
    return (entry["ts"], entry["row_number"])


def first_shortfall(
    timeline: list[dict], starting: dict[Any, Decimal]
) -> tuple[int, dt.datetime, Any] | None:
    """Dry-run the (already sorted) timeline against ``starting`` on-hand per location key.

    Each entry: {row_number, ts, kind, qty (Decimal, signed for adjustment), loc, to_loc}.
    Returns (row_number, ts, loc) of the FIRST movement that would drive a location's
    on-hand below zero, or None if the whole replay stays non-negative. Pure — no DB."""
    on_hand = dict(starting)

    def _get(loc: Any) -> Decimal:
        return on_hand.get(loc, Decimal("0"))

    for e in timeline:
        kind, qty, loc = e["kind"], e["qty"], e["loc"]
        if kind in _INFLOW:
            on_hand[loc] = _get(loc) + qty
        elif kind == KIND_SALE:
            if _get(loc) - qty < 0:
                return e["row_number"], e["ts"], loc
            on_hand[loc] = _get(loc) - qty
        elif kind == KIND_ADJUSTMENT:
            if _get(loc) + qty < 0:  # qty already signed
                return e["row_number"], e["ts"], loc
            on_hand[loc] = _get(loc) + qty
        elif kind == KIND_TRANSFER:
            if _get(loc) - qty < 0:
                return e["row_number"], e["ts"], loc
            on_hand[loc] = _get(loc) - qty
            on_hand[e["to_loc"]] = _get(e["to_loc"]) + qty
    return None


_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("row_type", "Type", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("type", "movement", "movement type", "transaction", "transaction type", "kind")),
    FieldSpec("timestamp", "Timestamp", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("timestamp", "datetime", "date", "date time", "moved at", "occurred at",
                       "transaction date", "movement date")),
    FieldSpec("product", "Product", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("product", "item", "sku", "item code", "product code", "part number",
                       "part no", "code", "item name", "product name")),
    FieldSpec("warehouse", "Warehouse", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("warehouse", "warehouse name", "location", "store", "site", "from",
                       "source", "from warehouse", "source warehouse", "warehouse code")),
    FieldSpec("to_warehouse", "To Warehouse", kind=FieldKind.STRING, levels=_ALL,
              aliases=("to warehouse", "destination", "dest", "to", "to location",
                       "destination warehouse")),
    FieldSpec("quantity", "Quantity", required=True, kind=FieldKind.DECIMAL, levels=_ALL,
              signed=True,
              aliases=("qty", "quantity", "units", "amount")),
    FieldSpec("unit_price", "Unit Price", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("unit price", "price", "selling price", "sale price")),
    FieldSpec("reason", "Reason / Reference", kind=FieldKind.STRING, levels=_STD,
              aliases=("reason", "reference", "note", "remarks", "document", "doc no")),
)


class _Repo:
    """Read-only matchers over the request session (RLS scopes to tenant)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.s = session
        self.tenant_id = tenant_id

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

    async def opening_as_of(self, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> dt.datetime | None:
        """The reconstructed opening moment for a product+warehouse (earliest opening_balance
        ledger entry), or None if no opening balance was set."""
        return await self.s.scalar(
            select(func.min(StockMovement.occurred_at)).where(
                StockMovement.product_id == product_id,
                StockMovement.warehouse_id == warehouse_id,
                StockMovement.movement_type == "opening_balance",
            )
        )


class StockReplayImporter(AtomicImporter):
    key = "stock_replay"
    label = "Transaction Replay (reconstruction)"
    key_field = "product"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    # ------------------------------- plan ------------------------------ #
    async def plan(
        self, session: Any, *, tenant_id: Any, rows: list[RowInput], options: Any = None
    ) -> ImportPlan:
        repo = _Repo(session, tenant_id)
        plan = ImportPlan()
        product_cache: dict[str, Product | None] = {}
        warehouse_cache: dict[str, Warehouse | None] = {}
        opening_cache: dict[tuple[uuid.UUID, uuid.UUID], dt.datetime | None] = {}
        onhand_cache: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}

        async def find_product(token: str) -> Product | None:
            nl = _norm(token)
            if nl not in product_cache:
                product_cache[nl] = await repo.find_product(token)
            return product_cache[nl]

        async def find_warehouse(token: str) -> Warehouse | None:
            nl = _norm(token)
            if nl not in warehouse_cache:
                warehouse_cache[nl] = await repo.find_warehouse(token)
            return warehouse_cache[nl]

        timeline: list[dict] = []
        for row_number, clean, field_errors in rows:
            errors = list(field_errors)

            kind = normalize_type(clean.get("row_type"))
            if clean.get("row_type") and kind is None:
                errors.append(f"Unknown movement type '{clean.get('row_type')}'")

            ts, ok = parse_timestamp(clean.get("timestamp"))
            if not ok:
                errors.append("Timestamp is required and must be a valid date/time")

            product = await find_product(clean["product"]) if clean.get("product") else None
            if clean.get("product") and product is None:
                errors.append(f"Product '{clean.get('product')}' not found - create it first")

            warehouse = await find_warehouse(clean["warehouse"]) if clean.get("warehouse") else None
            if clean.get("warehouse") and warehouse is None:
                errors.append(f"Warehouse '{clean.get('warehouse')}' not found - create it first")

            to_warehouse = None
            if kind in _TRANSFER_KINDS:
                raw_to = clean.get("to_warehouse")
                if not raw_to:
                    errors.append("A transfer needs a destination (To Warehouse)")
                else:
                    to_warehouse = await find_warehouse(raw_to)
                    if to_warehouse is None:
                        errors.append(f"Destination warehouse '{raw_to}' not found - create it first")
                    elif warehouse is not None and to_warehouse.id == warehouse.id:
                        errors.append("A transfer's source and destination must differ")
            elif clean.get("to_warehouse"):
                errors.append("Only a TRANSFER may have a To Warehouse")

            # quantity: adjustment is signed & non-zero; every other kind is strictly > 0.
            qty = clean.get("quantity")
            if qty is None:
                errors.append("Quantity is required")
            elif kind == KIND_ADJUSTMENT:
                if qty == 0:
                    errors.append("An adjustment quantity must be non-zero (+/-)")
            elif qty <= 0:
                errors.append("Quantity must be greater than zero")

            # no row may predate that product+warehouse's reconstructed opening balance
            if product is not None and warehouse is not None and ts is not None:
                key = (product.id, warehouse.id)
                if key not in opening_cache:
                    opening_cache[key] = await repo.opening_as_of(*key)
                opening = opening_cache[key]
                if opening is not None and ts < opening:
                    errors.append(
                        f"Movement dated {ts.date().isoformat()} predates the opening balance "
                        f"({opening.date().isoformat()}) for this product + warehouse"
                    )

            data = None
            if not errors:
                data = {
                    "kind": kind, "ts": ts, "product_id": product.id,
                    "warehouse_id": warehouse.id,
                    "to_warehouse_id": to_warehouse.id if to_warehouse else None,
                    "quantity": Decimal(str(qty)),
                    "reason": clean.get("reason"),
                }
                # signed value the dry-run applies (adjustment keeps its sign)
                loc = (product.id, warehouse.id)
                timeline.append({
                    "row_number": row_number, "ts": ts, "kind": kind,
                    "qty": Decimal(str(qty)), "loc": loc,
                    "to_loc": (product.id, to_warehouse.id) if to_warehouse else None,
                })
                for wid in (warehouse.id, to_warehouse.id if to_warehouse else None):
                    if wid is not None:
                        okey = (product.id, wid)
                        if okey not in onhand_cache:
                            onhand_cache[okey] = await repo.current_on_hand(*okey)
            plan.rows.append(RowPlan(row_number=row_number, key=clean.get("product"), errors=errors, data=data))

        # Chronological dry-run: STOP at the first movement that would go negative.
        if timeline:
            timeline.sort(key=sort_key)
            hit = first_shortfall(timeline, onhand_cache)
            if hit is not None:
                bad_row, bad_ts, _loc = hit
                for rp in plan.rows:
                    if rp.row_number == bad_row:
                        rp.errors.append(
                            f"Replaying this movement (dated {bad_ts.isoformat()}) would drive stock "
                            "negative — a receipt is missing or the rows are out of order. Replay stopped here."
                        )
                        rp.data = None
                        break

        return plan

    # ------------------------------ commit ----------------------------- #
    async def commit(self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan) -> int:
        inventory = InventoryService(
            InventoryRepository(session), ProductRepository(session),
            WarehouseRepository(session), AuditRepository(session), ReservationRepository(session),
        )
        # Process strictly in chronological order (NOT file order); ties by row number.
        ordered = sorted(
            (rp for rp in plan.rows if rp.data is not None),
            key=lambda rp: (rp.data["ts"], rp.row_number),
        )
        for rp in ordered:
            await self._apply(inventory, tenant_id, user_id, job_id, rp.data)
        await session.flush()
        return len(ordered)

    async def _apply(self, inv: InventoryService, tenant_id, user_id, job_id, d: dict) -> None:
        kind, ts = d["kind"], d["ts"]
        common = {"tenant_id": tenant_id, "user_id": user_id, "occurred_at": ts, "historical": True}
        if kind in _INFLOW:
            ref_type = "return" if kind == KIND_RETURN else "reconstruction_receipt"
            await inv.receive(
                req=ReceiveStockRequest(
                    warehouse_id=d["warehouse_id"], reference_type=ref_type, reference_id=job_id,
                    lines=[ReceiptLine(product_id=d["product_id"], quantity=d["quantity"])],
                ), **common,
            )
        elif kind == KIND_SALE:
            await inv.issue(
                req=IssueStockRequest(
                    warehouse_id=d["warehouse_id"], reference_type="reconstruction_sale",
                    reference_id=job_id, reason=d.get("reason") or "Reconstructed sale",
                    lines=[IssueLine(product_id=d["product_id"], quantity=d["quantity"])],
                ), **common,
            )
        elif kind == KIND_ADJUSTMENT:
            await inv.adjust(
                req=AdjustStockRequest(
                    warehouse_id=d["warehouse_id"], product_id=d["product_id"],
                    delta=d["quantity"], reason=d.get("reason") or "Reconstructed adjustment",
                ), **common,
            )
        elif kind == KIND_TRANSFER:
            await inv.transfer(
                req=TransferStockRequest(
                    product_id=d["product_id"], from_warehouse_id=d["warehouse_id"],
                    to_warehouse_id=d["to_warehouse_id"], quantity=d["quantity"],
                    reason=d.get("reason") or "Reconstructed transfer",
                ), **common,
            )

    # Not used for atomic targets (kept to satisfy the base contract).
    async def process_row(self, ctx: Any, clean: dict[str, Any]) -> RowResult:  # pragma: no cover
        raise NotImplementedError("stock_replay is an atomic target; use plan()/commit()")


register(StockReplayImporter())
