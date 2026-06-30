"""Motorcycle (serialized-unit) lifecycle orchestration.

Every accepted lifecycle transition is validated against the explicit state machine
(``domain/lifecycle.py``), written to the unit's immutable event ledger (from/to/user),
and recorded in ``audit_logs`` — illegal transitions are rejected. Selling reuses the
EXISTING sales documents: ``reserve``/``sell`` link the unit to a sales order / invoice
and set its customer + price; no parallel sales path is created. A branch move is a
serialized transfer recorded on the unit's ledger (both sides visible) — the transfer
concept, not the fungible stock engine.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import MotorcycleUnit
from app.motorcycles.domain import lifecycle as L
from app.motorcycles.repository import MotorcycleRepository
from app.motorcycles.schemas import (
    MotorcycleUnitCreate,
    MotorcycleUnitOut,
    MotorcycleUnitUpdate,
    ReserveIn,
    SellIn,
    TransferIn,
    TransitionIn,
    UnitEventOut,
)
from app.repositories.audit_repo import AuditRepository

_INVOICE_TO_PAYMENT = {"paid": "paid", "partially_paid": "partial"}


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


class MotorcycleService:
    def __init__(self, repo: MotorcycleRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------ create ----------------------------- #
    async def create_unit(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: MotorcycleUnitCreate
    ) -> MotorcycleUnitOut:
        if await self.repo.get_by_chassis(payload.chassis_number) is not None:
            raise BusinessRuleError(f"Chassis number {payload.chassis_number} already exists.")
        unit = MotorcycleUnit(
            tenant_id=tenant_id, chassis_number=payload.chassis_number,
            engine_number=payload.engine_number, model=payload.model, variant=payload.variant,
            colour=payload.colour, year=payload.year, supplier_id=payload.supplier_id,
            container_ref=payload.container_ref, date_received=payload.date_received,
            branch_id=payload.branch_id, warehouse_id=payload.warehouse_id,
            internal_location=payload.internal_location, status=L.RECEIVED,
            assembly_status="required" if payload.assembly_required else "not_required",
            selling_price=_d(payload.selling_price), notes=payload.notes, created_by=user_id,
        )
        self.repo.session.add(unit)
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="created",
            to_status=L.RECEIVED, user_id=user_id, note="Unit received",
        )
        await self._audit(tenant_id, user_id, unit.id, "created", None, L.RECEIVED)
        return await self._out(unit, with_events=True)

    # ------------------------------ update ----------------------------- #
    async def update_unit(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID,
        payload: MotorcycleUnitUpdate,
    ) -> MotorcycleUnitOut:
        unit = await self._require(unit_id, lock=True)
        self._check_version(unit, payload.version)
        fields = payload.model_dump(exclude_unset=True, exclude={"version"})
        for key, value in fields.items():
            setattr(unit, key, _d(value) if key == "selling_price" else value)
        unit.version += 1
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, unit.id, "updated", unit.status, unit.status,
                          extra={"fields": sorted(fields)})
        return await self._out(unit, with_events=True)

    # ---------------------------- transition --------------------------- #
    async def transition(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID, payload: TransitionIn
    ) -> MotorcycleUnitOut:
        unit = await self._require(unit_id, lock=True)
        new = payload.to_status
        if new in (L.RESERVED, L.SOLD):
            raise BusinessRuleError(
                "Use the reserve / sell action to set the customer and document linkage."
            )
        if not L.can_transition(unit.status, new):
            raise BusinessRuleError(f"Cannot move unit from {unit.status} to {new}.")
        old = unit.status
        unit.status = new
        self._apply_side_effects(unit, new)
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="status_change",
            from_status=old, to_status=new, user_id=user_id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, unit.id, f"status:{new}", old, new)
        return await self._out(unit, with_events=True)

    @staticmethod
    def _apply_side_effects(unit: MotorcycleUnit, new: str) -> None:
        """Keep the convenience fields consistent with the lifecycle position."""
        if new == L.INSPECTED and unit.inspection_status == "pending":
            unit.inspection_status = "passed"
        elif new == L.INSPECTED and unit.reserved:
            # releasing a hold (reserved -> inspected)
            unit.reserved = False
            unit.reserved_sales_order_id = None
        elif new == L.REGISTERED:
            unit.registration_status = "registered"
        elif new == L.WARRANTY_ACTIVE and unit.warranty_start is None:
            unit.warranty_start = dt.date.today()

    # ----------------------------- reserve ----------------------------- #
    async def reserve(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID, payload: ReserveIn
    ) -> MotorcycleUnitOut:
        unit = await self._require(unit_id, lock=True)
        if unit.status not in L.RESERVABLE_FROM:
            raise BusinessRuleError(f"A unit in status {unit.status} cannot be reserved.")
        if not await self.repo.customer_exists(payload.customer_id):
            raise NotFoundError("Customer not found")
        if payload.sales_order_id and await self.repo.get_sales_order(payload.sales_order_id) is None:
            raise NotFoundError("Sales order not found")
        old = unit.status
        unit.status = L.RESERVED
        unit.reserved = True
        unit.reserved_sales_order_id = payload.sales_order_id
        unit.customer_id = payload.customer_id
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="reserved", from_status=old,
            to_status=L.RESERVED, user_id=user_id, reference_type="sales_order",
            reference_id=payload.sales_order_id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, unit.id, "reserved", old, L.RESERVED)
        return await self._out(unit, with_events=True)

    # ------------------------------- sell ------------------------------ #
    async def sell(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID, payload: SellIn
    ) -> MotorcycleUnitOut:
        unit = await self._require(unit_id, lock=True)
        if unit.status not in L.SELLABLE_FROM:
            raise BusinessRuleError(f"A unit in status {unit.status} cannot be sold.")
        invoice = await self.repo.get_invoice(payload.invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        old = unit.status
        unit.status = L.SOLD
        unit.sold = True
        unit.reserved = False
        unit.invoice_id = invoice.id
        unit.customer_id = payload.customer_id or invoice.customer_id
        unit.price_charged = _d(payload.price_charged) if payload.price_charged is not None else _d(unit.selling_price)
        unit.payment_status = _INVOICE_TO_PAYMENT.get(invoice.status, "unpaid")
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="sold", from_status=old,
            to_status=L.SOLD, user_id=user_id, reference_type="invoice",
            reference_id=invoice.id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, unit.id, "sold", old, L.SOLD)
        return await self._out(unit, with_events=True)

    # ----------------------------- transfer ---------------------------- #
    async def transfer(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, unit_id: uuid.UUID, payload: TransferIn
    ) -> MotorcycleUnitOut:
        """Serialized branch move: this exact chassis moves to another branch/location.
        Recorded as a `transfer` event with from/to branch (both sides visible), audited.
        Reuses the transfer concept on the unit's own ledger — the fungible stock-transfer
        engine cannot represent a single serialized unit."""
        unit = await self._require(unit_id, lock=True)
        if unit.status == L.CANCELLED:
            raise BusinessRuleError("A cancelled unit cannot be transferred.")
        if payload.to_branch_id == unit.branch_id and payload.to_warehouse_id == unit.warehouse_id:
            raise BusinessRuleError("Destination is the same as the current location.")
        from_branch = unit.branch_id
        unit.branch_id = payload.to_branch_id
        if payload.to_warehouse_id is not None:
            unit.warehouse_id = payload.to_warehouse_id
        if payload.internal_location is not None:
            unit.internal_location = payload.internal_location
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="transfer", user_id=user_id,
            from_branch_id=from_branch, to_branch_id=payload.to_branch_id, note=payload.note,
        )
        await self._audit(tenant_id, user_id, unit.id, "transferred", unit.status, unit.status,
                          extra={"from_branch": str(from_branch), "to_branch": str(payload.to_branch_id)})
        return await self._out(unit, with_events=True)

    # ------------------------------ reads ------------------------------ #
    async def get_unit(self, unit_id: uuid.UUID) -> MotorcycleUnitOut:
        return await self._out(await self._require(unit_id), with_events=True)

    async def list_units(self, **filters) -> tuple[list[MotorcycleUnitOut], int]:
        rows, total = await self.repo.list(**filters)
        # Batch name resolution for the page.
        br = await self.repo.branch_names([u.branch_id for u in rows])
        wh = await self.repo.warehouse_names([u.warehouse_id for u in rows])
        cu = await self.repo.customer_names([u.customer_id for u in rows])
        out = [await self._out(u, with_events=False, names=(br, wh, {}, cu)) for u in rows]
        return out, total

    # ----------------------------- helpers ----------------------------- #
    async def _require(self, unit_id: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit:
        unit = await self.repo.get(unit_id, lock=lock)
        if unit is None:
            raise NotFoundError("Motorcycle unit not found")
        return unit

    @staticmethod
    def _check_version(unit: MotorcycleUnit, version: int | None) -> None:
        if version is not None and version != unit.version:
            raise BusinessRuleError(
                "This unit was changed by someone else since you loaded it; reload and retry."
            )

    async def _audit(self, tenant_id, user_id, unit_id, action, old, new, extra=None) -> None:
        changes = {"old_status": old, "new_status": new}
        if extra:
            changes.update(extra)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"motorcycle_unit.{action}",
            entity_type="motorcycle_unit", entity_id=unit_id, changes=changes,
        )

    async def _out(self, unit: MotorcycleUnit, *, with_events: bool, names=None) -> MotorcycleUnitOut:
        if names is None:
            br = await self.repo.branch_names([unit.branch_id])
            wh = await self.repo.warehouse_names([unit.warehouse_id])
            sup = await self.repo.supplier_names([unit.supplier_id])
            cu = await self.repo.customer_names([unit.customer_id])
        else:
            br, wh, sup, cu = names
        events: list[UnitEventOut] = []
        if with_events:
            ledger = await self.repo.events_for(unit.id)
            ev_branch_ids = [e.from_branch_id for e in ledger] + [e.to_branch_id for e in ledger]
            ebr = await self.repo.branch_names([b for b in ev_branch_ids if b])
            events = [
                UnitEventOut(
                    id=e.id, event_type=e.event_type, from_status=e.from_status, to_status=e.to_status,
                    from_branch_id=e.from_branch_id, from_branch_name=ebr.get(e.from_branch_id),
                    to_branch_id=e.to_branch_id, to_branch_name=ebr.get(e.to_branch_id),
                    reference_type=e.reference_type, reference_id=e.reference_id, note=e.note,
                    user_id=e.user_id, created_at=e.created_at,
                )
                for e in ledger
            ]
        return MotorcycleUnitOut(
            id=unit.id, chassis_number=unit.chassis_number, engine_number=unit.engine_number,
            model=unit.model, variant=unit.variant, colour=unit.colour, year=unit.year,
            supplier_id=unit.supplier_id, supplier_name=sup.get(unit.supplier_id),
            container_ref=unit.container_ref, date_received=unit.date_received,
            branch_id=unit.branch_id, branch_name=br.get(unit.branch_id),
            warehouse_id=unit.warehouse_id, warehouse_name=wh.get(unit.warehouse_id),
            internal_location=unit.internal_location, status=unit.status,
            inspection_status=unit.inspection_status, assembly_status=unit.assembly_status,
            reserved=unit.reserved, reserved_sales_order_id=unit.reserved_sales_order_id,
            so_number=await self.repo.so_number(unit.reserved_sales_order_id),
            sold=unit.sold, invoice_id=unit.invoice_id,
            invoice_number=await self.repo.invoice_number(unit.invoice_id),
            customer_id=unit.customer_id, customer_name=cu.get(unit.customer_id),
            selling_price=_f(unit.selling_price), price_charged=_f(unit.price_charged),
            payment_status=unit.payment_status, registration_status=unit.registration_status,
            registration_number=unit.registration_number,
            registration_papers_received=unit.registration_papers_received,
            warranty_start=unit.warranty_start, warranty_end=unit.warranty_end, notes=unit.notes,
            version=unit.version, created_at=unit.created_at, updated_at=unit.updated_at,
            allowed_next=L.allowed_next(unit.status), events=events,
        )
