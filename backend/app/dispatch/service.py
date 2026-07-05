"""Typed delivery / dispatch note orchestration.

A dispatch note is PAPER: it documents a stock movement but NEVER writes stock itself.
Parts move through ``InventoryService`` (the single qty_on_hand write path) — issued from
the source on dispatch, received at the destination on receipt. Bikes move through the
serialized motorcycle registry (they never touch qty_on_hand): on dispatch a unit leaves
the source (in transit), on receipt it lands at the destination branch (or is restored to
source if reported missing). The TYPE fixes the direction; there is no add/deduct toggle.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.dispatch.domain import status as S
from app.dispatch.repository import DispatchRepository
from app.dispatch.schemas import (
    DispatchLineOut,
    DispatchNoteCreate,
    DispatchNoteOut,
    DispatchReceive,
)
from app.models import DispatchNote, DispatchNoteLine, MotorcycleUnitEvent
from app.motorcycles.domain import lifecycle as L
from app.repositories.audit_repo import AuditRepository
from app.schemas.inventory import (
    IssueLine,
    IssueStockRequest,
    ReceiptLine,
    ReceiveStockRequest,
)
from app.services.inventory_service import InventoryService

_TYPES = frozenset({
    "warehouse_branch_transfer", "branch_branch_transfer",
    "customer_delivery", "internal_issuance",
})
# Types Type-1 PR implements end-to-end (a two-location transfer).
_TRANSFER_TYPES = frozenset({"warehouse_branch_transfer", "branch_branch_transfer"})


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class DispatchService:
    def __init__(self, repo: DispatchRepository, inventory: InventoryService, audit: AuditRepository) -> None:
        self.repo = repo
        # Stock moves ONLY through the inventory service (parts) / serialized registry
        # (bikes). This service orchestrates + documents; it never writes qty_on_hand.
        self.inventory = inventory
        self.audit = audit

    # ------------------------------- create ---------------------------------- #
    async def create(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: DispatchNoteCreate) -> DispatchNoteOut:
        if payload.dispatch_type not in _TRANSFER_TYPES:
            raise BusinessRuleError(
                f"Delivery-note type '{payload.dispatch_type}' is not available yet."
            )
        if payload.from_warehouse_id == payload.to_warehouse_id:
            raise BusinessRuleError("Source and destination locations must differ.")
        src = await self.repo.get_warehouse(payload.from_warehouse_id)
        dst = await self.repo.get_warehouse(payload.to_warehouse_id)
        if src is None:
            raise NotFoundError("Source warehouse not found")
        if dst is None:
            raise NotFoundError("Destination warehouse not found")

        note = DispatchNote(
            tenant_id=tenant_id, note_number=await self.repo.number(tenant_id),
            dispatch_type=payload.dispatch_type, status=S.DRAFT,
            from_branch_id=src.branch_id, from_warehouse_id=src.id,
            to_branch_id=dst.branch_id, to_warehouse_id=dst.id,
            remarks=payload.remarks, created_by=user_id,
        )
        lines: list[DispatchNoteLine] = []
        for pl in payload.part_lines:
            if await self.repo.get_product(pl.product_id) is None:
                raise NotFoundError("Product not found")
            lines.append(DispatchNoteLine(
                tenant_id=tenant_id, line_kind="part", product_id=pl.product_id,
                dispatched_qty=_d(pl.qty), remarks=pl.remarks,
            ))

        seen: set[uuid.UUID] = set()
        for bl in payload.bike_lines:
            unit = await self.repo.get_unit(bl.unit_id)
            if unit is None:
                raise NotFoundError("Motorcycle unit not found")
            if unit.id in seen:
                raise BusinessRuleError(f"Unit {unit.chassis_number} is listed more than once.")
            seen.add(unit.id)
            if unit.status == L.SOLD:
                raise BusinessRuleError(f"Unit {unit.chassis_number} is sold and cannot be transferred.")
            if unit.warehouse_id is not None and unit.warehouse_id != src.id:
                raise BusinessRuleError(f"Unit {unit.chassis_number} is not at the source location.")
            if await self.repo.unit_on_open_note(unit.id):
                raise BusinessRuleError(f"Unit {unit.chassis_number} is already on an open delivery note.")
            lines.append(DispatchNoteLine(
                tenant_id=tenant_id, line_kind="motorcycle", unit_id=unit.id,
                chassis_number=unit.chassis_number, engine_number=unit.engine_number,
                dispatched_qty=Decimal("1"), remarks=bl.remarks,
            ))

        note.lines = lines
        self.repo.session.add(note)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, note.id, "created",
                          {"type": note.dispatch_type, "lines": len(lines)})
        return await self._out(note)

    # ------------------------------- dispatch -------------------------------- #
    async def dispatch(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, note_id: uuid.UUID) -> DispatchNoteOut:
        note = await self._require(await self.repo.get(note_id, lock=True))
        if note.status != S.DRAFT:
            raise BusinessRuleError(f"Only a draft note can be dispatched (status={note.status}).")

        part_lines = [ln for ln in note.lines if ln.line_kind == "part"]
        if part_lines:
            # Single write path: decrement the source, one 'issue' movement per line.
            await self.inventory.issue(
                tenant_id=tenant_id, user_id=user_id,
                req=IssueStockRequest(
                    warehouse_id=note.from_warehouse_id,
                    lines=[IssueLine(product_id=ln.product_id, quantity=_d(ln.dispatched_qty)) for ln in part_lines],
                    reference_type="dispatch_note", reference_id=note.id,
                    reason=f"Delivery note {note.note_number}",
                ),
            )
        for ln in note.lines:
            if ln.line_kind == "motorcycle":
                unit = await self.repo.get_unit(ln.unit_id, lock=True)
                # The unit leaves the source and is in transit (at no branch) until receipt.
                unit.branch_id = None
                unit.warehouse_id = None
                unit.version += 1
                self.repo.session.add(MotorcycleUnitEvent(
                    tenant_id=tenant_id, unit_id=unit.id, event_type="transfer",
                    from_branch_id=note.from_branch_id, to_branch_id=note.to_branch_id,
                    reference_type="dispatch_note", reference_id=note.id,
                    note=f"Dispatched on {note.note_number}", user_id=user_id,
                ))

        note.status = S.IN_TRANSIT
        note.dispatched_by = user_id
        note.dispatched_at = _now()
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, note.id, "dispatched", {"status": note.status})
        return await self._out(note)

    # -------------------------------- receive -------------------------------- #
    async def receive(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, note_id: uuid.UUID, payload: DispatchReceive) -> DispatchNoteOut:
        note = await self._require(await self.repo.get(note_id, lock=True))
        if note.status not in S.RECEIVABLE:
            raise BusinessRuleError(f"This note is not awaiting receipt (status={note.status}).")

        part_recv = {r.line_id: r for r in payload.part_lines}
        bike_recv = {r.line_id: r for r in payload.bike_lines}

        for ln in note.lines:
            if ln.line_kind == "part":
                dispatched = _f(ln.dispatched_qty)
                r = part_recv.get(ln.id)
                if r is None:
                    received, damaged = dispatched, 0.0
                else:
                    received = min(max(0.0, r.received_qty), dispatched)
                    damaged = min(max(0.0, r.damaged_qty), dispatched - received)
                missing = max(0.0, dispatched - received - damaged)
                if received > 0:
                    # Single write path: increment the destination.
                    await self.inventory.receive(
                        tenant_id=tenant_id, user_id=user_id,
                        req=ReceiveStockRequest(
                            warehouse_id=note.to_warehouse_id,
                            lines=[ReceiptLine(product_id=ln.product_id, quantity=_d(received))],
                            reference_type="dispatch_note", reference_id=note.id,
                        ),
                    )
                ln.received_qty = _d(received)
                ln.damaged_qty = _d(damaged)
                ln.missing_qty = _d(missing)
            else:  # motorcycle
                r = bike_recv.get(ln.id)
                confirmed = True if r is None else bool(r.received)
                unit = await self.repo.get_unit(ln.unit_id, lock=True)
                if confirmed:
                    unit.branch_id = note.to_branch_id
                    unit.warehouse_id = note.to_warehouse_id
                    unit.version += 1
                    ln.received_qty = Decimal("1")
                    ln.missing_qty = Decimal("0")
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="transfer",
                        from_branch_id=note.from_branch_id, to_branch_id=note.to_branch_id,
                        reference_type="dispatch_note", reference_id=note.id,
                        note=f"Received on {note.note_number}", user_id=user_id,
                    ))
                else:
                    # Missing in transit — restore the unit to the source location.
                    unit.branch_id = note.from_branch_id
                    unit.warehouse_id = note.from_warehouse_id
                    unit.version += 1
                    ln.received_qty = Decimal("0")
                    ln.missing_qty = Decimal("1")
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="transfer",
                        from_branch_id=None, to_branch_id=note.from_branch_id,
                        reference_type="dispatch_note", reference_id=note.id,
                        note=f"Reported missing on {note.note_number} — restored to source", user_id=user_id,
                    ))

        note.status = S.receive_outcome([
            (_f(ln.dispatched_qty), _f(ln.received_qty), _f(ln.missing_qty), _f(ln.damaged_qty))
            for ln in note.lines
        ])
        note.received_by = payload.received_by
        note.received_by_user = user_id
        note.received_at = _now()
        if payload.remarks:
            note.remarks = payload.remarks
        await self.repo.session.flush()
        short = sum(_f(ln.missing_qty) + _f(ln.damaged_qty) for ln in note.lines)
        await self._audit(tenant_id, user_id, note.id, "received",
                          {"status": note.status, "shortfall": short})
        return await self._out(note)

    async def cancel(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, note_id: uuid.UUID, reason: str | None) -> DispatchNoteOut:
        note = await self._require(await self.repo.get(note_id, lock=True))
        if note.status not in S.CANCELLABLE:
            raise BusinessRuleError(f"Only a draft note can be cancelled (status={note.status}).")
        note.status = S.CANCELLED
        if reason:
            note.remarks = reason
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, note.id, "cancelled", {"reason": reason})
        return await self._out(note)

    # -------------------------------- reads ---------------------------------- #
    async def get(self, note_id: uuid.UUID) -> DispatchNoteOut:
        return await self._out(await self._require(await self.repo.get(note_id)))

    async def list_notes(self, **f) -> list[DispatchNoteOut]:
        return [await self._out(n) for n in await self.repo.list_notes(**f)]

    # ------------------------------- helpers --------------------------------- #
    @staticmethod
    async def _require(note: DispatchNote | None) -> DispatchNote:
        if note is None:
            raise NotFoundError("Delivery note not found")
        return note

    async def _audit(self, tenant_id, user_id, note_id, action, changes) -> None:
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"dispatch_note.{action}",
            entity_type="dispatch_note", entity_id=note_id, changes=changes,
        )

    async def _out(self, note: DispatchNote) -> DispatchNoteOut:
        branches = await self.repo.branch_names([note.from_branch_id, note.to_branch_id])
        warehouses = await self.repo.warehouse_names([note.from_warehouse_id, note.to_warehouse_id])
        prod = await self.repo.product_index([ln.product_id for ln in note.lines])
        unit_models = await self.repo.unit_model_ids([ln.unit_id for ln in note.lines])
        model_names = await self.repo.model_names(list(unit_models.values()))
        lines = []
        for ln in note.lines:
            sku, name = prod.get(ln.product_id, (None, None))
            model_name = model_names.get(unit_models.get(ln.unit_id)) if ln.unit_id else None
            lines.append(DispatchLineOut(
                id=ln.id, line_kind=ln.line_kind, product_id=ln.product_id, sku=sku, name=name,
                unit_id=ln.unit_id, chassis_number=ln.chassis_number, engine_number=ln.engine_number,
                model_name=model_name, dispatched_qty=_f(ln.dispatched_qty), received_qty=_f(ln.received_qty),
                missing_qty=_f(ln.missing_qty), damaged_qty=_f(ln.damaged_qty), remarks=ln.remarks,
            ))
        return DispatchNoteOut(
            id=note.id, note_number=note.note_number, dispatch_type=note.dispatch_type, status=note.status,
            from_branch_id=note.from_branch_id, from_branch_name=branches.get(note.from_branch_id),
            from_warehouse_id=note.from_warehouse_id, from_warehouse_name=warehouses.get(note.from_warehouse_id),
            to_branch_id=note.to_branch_id, to_branch_name=branches.get(note.to_branch_id),
            to_warehouse_id=note.to_warehouse_id, to_warehouse_name=warehouses.get(note.to_warehouse_id),
            remarks=note.remarks, dispatched_by=note.dispatched_by, dispatched_at=note.dispatched_at,
            received_by=note.received_by, received_at=note.received_at, created_at=note.created_at, lines=lines,
        )
