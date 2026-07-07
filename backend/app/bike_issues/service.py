"""Bike-issues orchestration: an internal repair on a bike we OWN that has a fault.

This is deliberately NOT a sale. Customers buy parts only through POS / sales. Here a
bike in our own stock is faulty and we take spare part(s) from our own inventory to fix
it — the part is an internal cost, with no invoice and no customer.

Two invariants this service upholds:

  * ONE stock write path. Every consumed part is deducted by ``InventoryService.issue``
    (lock row, check available, decrement qty_on_hand once, write the immutable
    stock_movements ledger entry, audit). This module NEVER writes ``qty_on_hand``. The
    movement is tagged ``reference_type='bike_repair'`` so reports can tell a repair
    consumption apart from a POS sale (which uses ``sales_delivery`` + an invoice).
  * The bike can't be sold mid-repair. Opening an issue routes the unit to ``on_hold``
    (reusing the serialized lifecycle, with the issue as the hold reason); resolving
    returns it to its prior sellable status. Both transitions are written to the unit's
    own event ledger.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.bike_issues.domain import status as S
from app.bike_issues.repository import BikeIssueRepository
from app.bike_issues.schemas import (
    BikeIssueCreate,
    BikeIssueOut,
    BikeIssueResolve,
    RepairLineIn,
    RepairLineOut,
)
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import BikeIssue, BikeIssueLine
from app.motorcycles.domain import lifecycle as L
from app.repositories.audit_repo import AuditRepository
from app.schemas.inventory import IssueLine, IssueStockRequest
from app.services.inventory_service import InventoryService

# The movement tag that marks a stock deduction as an internal repair consumption —
# distinct from a POS sale ('sales_delivery'). Lets reports separate the two.
REPAIR_REF = "bike_repair"

# A bike can only be pulled into repair from a sellable, in-stock status (the two states
# the lifecycle lets us move to on_hold from). Sold / reserved / already-on-hold are out.
OPENABLE_FROM = frozenset({L.UNASSEMBLED, L.ASSEMBLED})


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class BikeIssueService:
    def __init__(self, repo: BikeIssueRepository, inventory: InventoryService, audit: AuditRepository) -> None:
        self.repo = repo
        # Stock moves ONLY through the inventory service (single write path). This service
        # orchestrates + documents the repair and the serialized hold.
        self.inventory = inventory
        self.audit = audit

    # ------------------------------- create ---------------------------------- #
    async def open(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: BikeIssueCreate) -> BikeIssueOut:
        unit = await self.repo.get_unit(payload.unit_id, lock=True)
        if unit is None:
            raise NotFoundError("Motorcycle unit not found")
        if unit.status == L.SOLD:
            raise BusinessRuleError(f"Unit {unit.chassis_number} is sold and cannot be taken in for repair.")
        if unit.status not in OPENABLE_FROM:
            raise BusinessRuleError(
                f"Unit {unit.chassis_number} is {unit.status} and cannot be put on hold for repair "
                "(it must be a sellable, in-stock unit)."
            )

        issue = BikeIssue(
            tenant_id=tenant_id,
            issue_number=await self.repo.number(tenant_id),
            status=S.OPEN,
            unit_id=unit.id,
            chassis_number=unit.chassis_number,   # read from the unit, never retyped
            engine_number=unit.engine_number,
            branch_id=unit.branch_id,
            prior_status=unit.status,
            problem_description=payload.problem_description.strip(),
            reported_at=payload.reported_at or _now(),
            reported_by=user_id,
            notes=payload.notes,
        )
        issue.lines = [await self._build_line(tenant_id, ln) for ln in payload.lines]
        self.repo.session.add(issue)
        await self.repo.session.flush()

        # Hold the bike so it can't be sold mid-repair; record it on the unit's ledger.
        await self._hold_unit(tenant_id, user_id, unit, issue)
        await self._audit(tenant_id, user_id, issue.id, "opened",
                          {"unit_id": str(unit.id), "chassis": unit.chassis_number, "lines": len(issue.lines)})
        return await self._out(issue)

    # ------------------------------ edit lines ------------------------------- #
    async def add_line(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issue_id: uuid.UUID, payload: RepairLineIn
    ) -> BikeIssueOut:
        issue = await self._require(await self.repo.get(issue_id, lock=True))
        self._require_active(issue)
        issue.lines.append(await self._build_line(tenant_id, payload))
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, issue.id, "line_added", {"product_id": str(payload.product_id)})
        return await self._out(issue)

    async def remove_line(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issue_id: uuid.UUID, line_id: uuid.UUID
    ) -> BikeIssueOut:
        issue = await self._require(await self.repo.get(issue_id, lock=True))
        self._require_active(issue)
        line = next((ln for ln in issue.lines if ln.id == line_id), None)
        if line is None:
            raise NotFoundError("Repair line not found")
        if line.consumed:
            raise BusinessRuleError("A consumed repair line cannot be removed.")
        issue.lines.remove(line)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, issue.id, "line_removed", {"line_id": str(line_id)})
        return await self._out(issue)

    # ------------------------------ set status ------------------------------- #
    async def set_status(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issue_id: uuid.UUID, new_status: str
    ) -> BikeIssueOut:
        """Move between the non-terminal statuses (open <-> in_repair). Resolving has its
        own action because it commits stock and releases the bike."""
        issue = await self._require(await self.repo.get(issue_id, lock=True))
        if new_status == S.RESOLVED:
            raise BusinessRuleError("Use the resolve action to close a repair (it commits the part consumption).")
        if new_status not in S.STATUSES:
            raise BusinessRuleError(f"Unknown status '{new_status}'.")
        if new_status == issue.status:
            return await self._out(issue)
        if not S.can_transition(issue.status, new_status):
            raise BusinessRuleError(f"Cannot move a bike issue from {issue.status} to {new_status}.")
        issue.status = new_status
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, issue.id, f"status:{new_status}", {"status": new_status})
        return await self._out(issue)

    # ------------------------------- resolve --------------------------------- #
    async def resolve(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, issue_id: uuid.UUID, payload: BikeIssueResolve
    ) -> BikeIssueOut:
        """Close the repair: COMMIT the part consumption through the single inventory write
        path and return the bike to its prior sellable status. Atomic — if any part is
        short, the whole resolve is rejected (no negative stock, no partial consumption,
        the bike stays on hold)."""
        issue = await self._require(await self.repo.get(issue_id, lock=True))
        if issue.status not in S.RESOLVABLE_FROM:
            raise BusinessRuleError(f"This issue is already {issue.status}.")

        for ln in payload.lines:
            issue.lines.append(await self._build_line(tenant_id, ln))
        await self.repo.session.flush()

        for ln in issue.lines:
            if ln.consumed:
                continue
            # The ONE stock write path. Raises (rolling back the whole resolve) on shortfall.
            await self.inventory.issue(
                tenant_id=tenant_id, user_id=user_id,
                req=IssueStockRequest(
                    warehouse_id=ln.warehouse_id,
                    lines=[IssueLine(product_id=ln.product_id, quantity=_d(ln.quantity))],
                    reference_type=REPAIR_REF, reference_id=issue.id,
                    reason=f"Bike repair {issue.issue_number} — chassis {issue.chassis_number}",
                ),
            )
            ln.consumed = True
            ln.consumed_at = _now()

        await self._release_unit(tenant_id, user_id, issue)
        issue.status = S.RESOLVED
        issue.resolved_by = user_id
        issue.resolved_at = _now()
        if payload.resolution_note:
            issue.resolution_note = payload.resolution_note
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, issue.id, "resolved",
                          {"parts_consumed": sum(1 for ln in issue.lines)})
        return await self._out(issue)

    # -------------------------------- reads ---------------------------------- #
    async def get(self, issue_id: uuid.UUID) -> BikeIssueOut:
        return await self._out(await self._require(await self.repo.get(issue_id)))

    async def list_issues(self, **f) -> tuple[list[BikeIssueOut], int]:
        rows, total = await self.repo.list_issues(**f)
        return [await self._out(i) for i in rows], total

    # ---------------------------- serialized hold ---------------------------- #
    async def _hold_unit(self, tenant_id, user_id, unit, issue: BikeIssue) -> None:
        old = unit.status
        unit.status = L.ON_HOLD               # reuse the existing hold status
        unit.hold_reason = f"Repair {issue.issue_number}: {issue.problem_description}"
        unit.customer_id = None               # on_hold carries no customer
        unit.reserved_ref = None
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_unit_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="status_change",
            from_status=old, to_status=L.ON_HOLD, reference_type="bike_issue", reference_id=issue.id,
            note=f"On hold for repair {issue.issue_number}", user_id=user_id,
        )

    async def _release_unit(self, tenant_id, user_id, issue: BikeIssue) -> None:
        """Return the unit to the sellable status it held before the repair. Only acts if
        the unit is still on hold for THIS repair; if someone else has since moved it we
        leave its status alone (and just close the issue)."""
        unit = await self.repo.get_unit(issue.unit_id, lock=True)
        if unit is None or unit.status != L.ON_HOLD:
            return
        target = issue.prior_status if issue.prior_status in OPENABLE_FROM else L.ASSEMBLED
        if not L.can_transition(L.ON_HOLD, target):
            target = L.ASSEMBLED
        unit.status = target
        unit.hold_reason = None
        unit.version += 1
        await self.repo.session.flush()
        await self.repo.add_unit_event(
            tenant_id=tenant_id, unit_id=unit.id, event_type="status_change",
            from_status=L.ON_HOLD, to_status=target, reference_type="bike_issue", reference_id=issue.id,
            note=f"Repair {issue.issue_number} resolved", user_id=user_id,
        )

    # ------------------------------- helpers --------------------------------- #
    async def _build_line(self, tenant_id: uuid.UUID, ln: RepairLineIn) -> BikeIssueLine:
        if await self.repo.get_product(ln.product_id) is None:
            raise NotFoundError("Product not found")
        if await self.repo.get_warehouse(ln.warehouse_id) is None:
            raise NotFoundError("Source warehouse not found")
        return BikeIssueLine(
            tenant_id=tenant_id, product_id=ln.product_id, warehouse_id=ln.warehouse_id,
            quantity=_d(ln.quantity), consumed=False, remarks=ln.remarks,
        )

    @staticmethod
    def _require_active(issue: BikeIssue) -> None:
        if issue.status not in S.ACTIVE:
            raise BusinessRuleError(f"A {issue.status} issue's repair lines cannot be changed.")

    @staticmethod
    async def _require(issue: BikeIssue | None) -> BikeIssue:
        if issue is None:
            raise NotFoundError("Bike issue not found")
        return issue

    async def _audit(self, tenant_id, user_id, issue_id, action, changes) -> None:
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"bike_issue.{action}",
            entity_type="bike_issue", entity_id=issue_id, changes=changes,
        )

    async def _out(self, issue: BikeIssue) -> BikeIssueOut:
        branches = await self.repo.branch_names([issue.branch_id])
        warehouses = await self.repo.warehouse_names([ln.warehouse_id for ln in issue.lines])
        prod = await self.repo.product_index([ln.product_id for ln in issue.lines])
        model_names = await self.repo.unit_model_names([issue.unit_id])
        lines = []
        for ln in issue.lines:
            sku, name = prod.get(ln.product_id, (None, None))
            lines.append(RepairLineOut(
                id=ln.id, product_id=ln.product_id, sku=sku, name=name,
                warehouse_id=ln.warehouse_id, warehouse_name=warehouses.get(ln.warehouse_id),
                quantity=_f(ln.quantity), consumed=ln.consumed, consumed_at=ln.consumed_at, remarks=ln.remarks,
            ))
        return BikeIssueOut(
            id=issue.id, issue_number=issue.issue_number, status=issue.status,
            unit_id=issue.unit_id, chassis_number=issue.chassis_number, engine_number=issue.engine_number,
            model_name=model_names.get(issue.unit_id),
            branch_id=issue.branch_id, branch_name=branches.get(issue.branch_id),
            prior_status=issue.prior_status, problem_description=issue.problem_description,
            reported_at=issue.reported_at, reported_by=issue.reported_by,
            resolved_at=issue.resolved_at, resolved_by=issue.resolved_by,
            resolution_note=issue.resolution_note, notes=issue.notes,
            created_at=issue.created_at, lines=lines,
        )
