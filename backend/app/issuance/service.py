"""Internal issuance / handover orchestration (out-and-back loan).

An issuance NEVER sells and NEVER permanently deducts RETURNABLE stock — it makes the
issued thing temporarily not-sellable, then returns it. It writes NO stock directly:

  * serialized bikes: an OPEN issuance line marks the unit out-on-loan (derived into
    availability by the motorcycle sale path — NOT a 6th status, NOT `on_hold`). A clean
    return frees it; a "needs attention" (damaged) return routes it to `on_hold`.
  * fungible items: the qty is HELD via the reservation mechanism (qty_reserved up,
    qty_on_hand unchanged, so AVAILABLE drops). Return releases it; an unreturned
    shortfall is converted to a documented loss (a real deduction), never absorbed.
  * consumable / non-returnable items: issued for real at handover (a deduction), not
    expected back.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.issuance.domain import status as S
from app.issuance.repository import IssuanceRepository
from app.issuance.schemas import (
    IssuanceCreate,
    IssuanceLineOut,
    IssuanceOut,
    IssuanceReturn,
)
from app.models import Issuance, IssuanceLine, MotorcycleUnitEvent
from app.motorcycles.domain import lifecycle as L
from app.repositories.audit_repo import AuditRepository
from app.schemas.inventory import IssueLine, IssueStockRequest
from app.services.inventory_service import InventoryService, _available

_LINE_REF = "issuance_line"


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class IssuanceService:
    def __init__(self, repo: IssuanceRepository, inventory: InventoryService, audit: AuditRepository) -> None:
        self.repo = repo
        # Stock moves ONLY through the inventory service + reservation repo (fungible) and
        # the serialized registry (bikes). This service orchestrates + documents.
        self.inventory = inventory
        self.audit = audit

    # ------------------------------- create ---------------------------------- #
    async def create(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: IssuanceCreate) -> IssuanceOut:
        wh = await self.repo.get_warehouse(payload.warehouse_id)
        if wh is None:
            raise NotFoundError("Warehouse not found")
        iss = Issuance(
            tenant_id=tenant_id, issuance_number=await self.repo.number(tenant_id), status=S.DRAFT,
            branch_id=wh.branch_id, warehouse_id=wh.id, requestor=payload.requestor,
            department=payload.department, purpose=payload.purpose,
            expected_return_date=payload.expected_return_date, remarks=payload.remarks, created_by=user_id,
        )
        lines: list[IssuanceLine] = []
        for pl in payload.part_lines:
            if await self.repo.get_product(pl.product_id) is None:
                raise NotFoundError("Product not found")
            lines.append(IssuanceLine(
                tenant_id=tenant_id, line_kind="part", product_id=pl.product_id, qty=_d(pl.qty),
                returnable=pl.returnable and not pl.consumable, consumable=pl.consumable, remarks=pl.remarks,
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
                raise BusinessRuleError(f"Unit {unit.chassis_number} is sold and cannot be issued.")
            if await self.repo.unit_out_on_loan(unit.id):
                raise BusinessRuleError(f"Unit {unit.chassis_number} is already out on loan.")
            lines.append(IssuanceLine(
                tenant_id=tenant_id, line_kind="motorcycle", unit_id=unit.id,
                chassis_number=unit.chassis_number, engine_number=unit.engine_number, qty=Decimal("1"),
                returnable=True, consumable=False,
                odometer_out=_d(bl.odometer_out) if bl.odometer_out is not None else None,
                fuel_out=bl.fuel_out, accessories=bl.accessories, remarks=bl.remarks,
            ))
        iss.lines = lines
        self.repo.session.add(iss)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, iss.id, "created", {"lines": len(lines)})
        return await self._out(iss)

    # -------------------------------- issue ---------------------------------- #
    async def issue(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issuance_id: uuid.UUID) -> IssuanceOut:
        iss = await self._require(await self.repo.get(issuance_id, lock=True))
        if iss.status != S.DRAFT:
            raise BusinessRuleError(f"Only a draft issuance can be issued (status={iss.status}).")
        for ln in iss.lines:
            if ln.line_kind == "part":
                if ln.consumable:
                    # Non-returnable -> a real deduction at handover (single write path).
                    await self.inventory.issue(
                        tenant_id=tenant_id, user_id=user_id,
                        req=IssueStockRequest(
                            warehouse_id=iss.warehouse_id,
                            lines=[IssueLine(product_id=ln.product_id, quantity=_d(ln.qty))],
                            reference_type="issuance", reference_id=iss.id,
                            reason=f"Issuance {iss.issuance_number} (consumable handover)",
                        ),
                    )
                else:
                    # Returnable -> HOLD the qty (available down, on_hand unchanged).
                    inv = await self.inventory.inventory.get_for_update(ln.product_id, iss.warehouse_id)
                    avail = _available(inv) if inv is not None else Decimal("0")
                    if inv is None or avail < _d(ln.qty):
                        raise BusinessRuleError(
                            "Insufficient available stock to issue on loan",
                            details={"product_id": str(ln.product_id), "available": str(avail), "requested": str(ln.qty)},
                        )
                    await self.inventory.reservations.reserve(
                        tenant_id=tenant_id, inv=inv, qty=_d(ln.qty),
                        reference_id=ln.id, reference_type=_LINE_REF, user_id=user_id,
                    )
            else:  # motorcycle — the open line marks it out-on-loan (no stock change)
                unit = await self.repo.get_unit(ln.unit_id, lock=True)
                unit.version += 1
                self.repo.session.add(MotorcycleUnitEvent(
                    tenant_id=tenant_id, unit_id=unit.id, event_type="issued",
                    reference_type="issuance", reference_id=iss.id,
                    note=f"Issued out on loan — {iss.issuance_number}", user_id=user_id,
                ))
        iss.status = S.OUT_ON_LOAN
        iss.issued_by = user_id
        iss.issued_at = _now()
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, iss.id, "issued", {"status": iss.status})
        return await self._out(iss)

    # -------------------------------- return --------------------------------- #
    async def return_items(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issuance_id: uuid.UUID, payload: IssuanceReturn) -> IssuanceOut:
        iss = await self._require(await self.repo.get(issuance_id, lock=True))
        if iss.status not in S.RETURNABLE_STATES:
            raise BusinessRuleError(f"This issuance is not out on loan (status={iss.status}).")
        part_ret = {r.line_id: r for r in payload.part_lines}
        bike_ret = {r.line_id: r for r in payload.bike_lines}

        for ln in iss.lines:
            if ln.returned_at is not None or ln.consumable:
                continue  # already returned, or never expected back
            if ln.line_kind == "part":
                r = part_ret.get(ln.id)
                if r is None:
                    continue  # not part of THIS return — stays out on loan
                qty = _f(ln.qty)
                returned = min(max(0.0, r.returned_qty), qty)
                missing = max(0.0, qty - returned)
                await self._settle_part_return(tenant_id, user_id, ln, iss.warehouse_id, _d(missing))
                ln.returned_qty = _d(returned)
                ln.missing_qty = _d(missing)
                ln.returned_at = _now()
            else:  # motorcycle
                r = bike_ret.get(ln.id)
                if r is None:
                    continue
                unit = await self.repo.get_unit(ln.unit_id, lock=True)
                if r.condition == S.NEEDS_ATTENTION:
                    # Quarantine: route to on_hold with the return note as the hold reason
                    # (a damaged bike must not be sellable until checked).
                    old = unit.status
                    unit.status = L.ON_HOLD
                    unit.hold_reason = (r.return_note or "Returned needing attention")
                    unit.customer_id = None
                    unit.reserved_ref = None
                    unit.version += 1
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="status_change",
                        from_status=old, to_status=L.ON_HOLD, reference_type="issuance", reference_id=iss.id,
                        note=f"Returned needing attention on {iss.issuance_number}: {unit.hold_reason}", user_id=user_id,
                    ))
                else:
                    # Clean return — the closed line frees the unit for sale again.
                    unit.version += 1
                    self.repo.session.add(MotorcycleUnitEvent(
                        tenant_id=tenant_id, unit_id=unit.id, event_type="returned",
                        reference_type="issuance", reference_id=iss.id,
                        note=f"Returned from loan {iss.issuance_number} ({r.condition})", user_id=user_id,
                    ))
                ln.returned_qty = Decimal("1")
                ln.condition = r.condition
                ln.odometer_in = _d(r.odometer_in) if r.odometer_in is not None else None
                ln.return_note = r.return_note
                ln.returned_at = _now()

        returnable = [ln for ln in iss.lines if ln.returnable and not ln.consumable]
        iss.status = S.return_outcome([
            (_f(ln.qty), _f(ln.returned_qty) + _f(ln.missing_qty) if ln.returned_at else 0.0)
            for ln in returnable
        ])
        if iss.status == S.RETURNED:
            iss.closed_at = _now()
        if payload.remarks:
            iss.remarks = payload.remarks
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, iss.id, "returned", {"status": iss.status})
        return await self._out(iss)

    async def _settle_part_return(self, tenant_id, user_id, line, warehouse_id, missing: Decimal) -> None:
        """Convert an unreturned shortfall to a documented loss (deduct on_hand + consume
        that much of the hold), then release the remaining (returned) hold to available."""
        if missing > 0:
            await self.inventory.issue_against_reservation(
                tenant_id=tenant_id, user_id=user_id, product_id=line.product_id,
                warehouse_id=warehouse_id, quantity=missing, reference_type="issuance_loss",
                reference_id=line.id, reason="Unreturned issuance loss",
                reservation_ref=line.id, reservation_ref_type=_LINE_REF,
            )
        reservation = await self.inventory.reservations.active_for(line.id, _LINE_REF)
        if reservation is not None and reservation.qty > 0:
            inv = await self.inventory.inventory.get_for_update(line.product_id, warehouse_id)
            await self.inventory.reservations.release(
                tenant_id=tenant_id, inv=inv, reservation=reservation, user_id=user_id,
            )

    async def cancel(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issuance_id: uuid.UUID, reason: str | None) -> IssuanceOut:
        iss = await self._require(await self.repo.get(issuance_id, lock=True))
        if iss.status not in S.CANCELLABLE:
            raise BusinessRuleError(f"Only a draft issuance can be cancelled (status={iss.status}).")
        iss.status = S.CANCELLED
        if reason:
            iss.remarks = reason
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, iss.id, "cancelled", {"reason": reason})
        return await self._out(iss)

    # -------------------------------- reads ---------------------------------- #
    async def get(self, issuance_id: uuid.UUID) -> IssuanceOut:
        return await self._out(await self._require(await self.repo.get(issuance_id)))

    async def list_issuances(self, **f) -> list[IssuanceOut]:
        return [await self._out(i) for i in await self.repo.list_issuances(**f)]

    # ------------------------------- helpers --------------------------------- #
    @staticmethod
    async def _require(iss: Issuance | None) -> Issuance:
        if iss is None:
            raise NotFoundError("Issuance not found")
        return iss

    async def _audit(self, tenant_id, user_id, iid, action, changes) -> None:
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"issuance.{action}",
            entity_type="issuance", entity_id=iid, changes=changes,
        )

    async def _out(self, iss: Issuance) -> IssuanceOut:
        branches = await self.repo.branch_names([iss.branch_id])
        warehouses = await self.repo.warehouse_names([iss.warehouse_id])
        prod = await self.repo.product_index([ln.product_id for ln in iss.lines])
        unit_models = await self.repo.unit_model_ids([ln.unit_id for ln in iss.lines])
        model_names = await self.repo.model_names(list(unit_models.values()))
        lines = []
        for ln in iss.lines:
            sku, name = prod.get(ln.product_id, (None, None))
            model_name = model_names.get(unit_models.get(ln.unit_id)) if ln.unit_id else None
            lines.append(IssuanceLineOut(
                id=ln.id, line_kind=ln.line_kind, product_id=ln.product_id, sku=sku, name=name,
                unit_id=ln.unit_id, chassis_number=ln.chassis_number, engine_number=ln.engine_number,
                model_name=model_name, qty=_f(ln.qty), returnable=ln.returnable, consumable=ln.consumable,
                odometer_out=_f(ln.odometer_out) if ln.odometer_out is not None else None,
                fuel_out=ln.fuel_out, accessories=ln.accessories, returned_qty=_f(ln.returned_qty),
                missing_qty=_f(ln.missing_qty), condition=ln.condition,
                odometer_in=_f(ln.odometer_in) if ln.odometer_in is not None else None,
                return_note=ln.return_note, returned_at=ln.returned_at, remarks=ln.remarks,
            ))
        overdue = (
            iss.status in S.OPEN and iss.expected_return_date is not None
            and iss.expected_return_date < dt.date.today()
        )
        return IssuanceOut(
            id=iss.id, issuance_number=iss.issuance_number, status=iss.status,
            branch_id=iss.branch_id, branch_name=branches.get(iss.branch_id),
            warehouse_id=iss.warehouse_id, warehouse_name=warehouses.get(iss.warehouse_id),
            requestor=iss.requestor, department=iss.department, purpose=iss.purpose,
            expected_return_date=iss.expected_return_date, overdue=overdue, remarks=iss.remarks,
            issued_by=iss.issued_by, issued_at=iss.issued_at, closed_at=iss.closed_at,
            created_at=iss.created_at, lines=lines,
        )
