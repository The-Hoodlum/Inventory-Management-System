"""Bike-issues service flows.

The key guarantees under test: a repair CONSUMES its parts through the real
InventoryService (qty_on_hand down exactly once, one ledger entry tagged an internal
repair — never a sale), a short part is rejected with no negative stock, and the bike is
put on_hold when the issue opens and returned to its prior sellable status when it
resolves. Chassis/engine are read from the unit, never from the caller.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bike_issues.domain import status as S
from app.bike_issues.schemas import BikeIssueCreate, BikeIssueResolve, RepairLineIn
from app.bike_issues.service import REPAIR_REF, BikeIssueService
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.motorcycles.domain import lifecycle as L
from app.services.inventory_service import InventoryService
from tests.conftest import FakeAuditRepo, FakeInventoryRepo, FakeLookup

TENANT = uuid.uuid4()
USER = uuid.uuid4()
BRANCH = uuid.uuid4()
WH = uuid.uuid4()
PART = uuid.uuid4()


class _Session:
    """Assigns ids/timestamps on flush the way the DB defaults would, and registers
    created issues so ``repo.get()`` can find them (a real session would persist them)."""

    def __init__(self, issues: dict) -> None:
        self._tracked: list = []
        self._issues = issues

    def add(self, obj) -> None:
        self._tracked.append(obj)

    async def flush(self) -> None:
        import datetime as dt

        for obj in self._tracked:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
                obj.created_at = dt.datetime.now(dt.UTC)
            for ln in getattr(obj, "lines", None) or []:
                if getattr(ln, "id", None) is None:
                    ln.id = uuid.uuid4()
            if hasattr(obj, "issue_number"):
                self._issues[obj.id] = obj


class FakeBikeIssueRepo:
    def __init__(self, unit) -> None:
        self._issues: dict[uuid.UUID, object] = {}
        self.session = _Session(self._issues)
        self._unit = unit
        self.unit_events: list = []

    async def number(self, tenant_id):
        return "REP-2026-00001"

    def _remember(self, issue):
        if issue.id is not None:
            self._issues[issue.id] = issue

    async def get(self, issue_id, *, lock=False):
        return self._issues.get(issue_id)

    async def list_issues(self, **f):
        rows = list(self._issues.values())
        return rows, len(rows)

    async def get_product(self, pid):
        return SimpleNamespace(id=pid) if pid == PART else None

    async def get_warehouse(self, wid):
        return SimpleNamespace(id=wid) if wid == WH else None

    async def get_unit(self, unit_id, *, lock=False):
        return self._unit if unit_id == self._unit.id else None

    async def add_unit_event(self, **kwargs):
        ev = SimpleNamespace(id=uuid.uuid4(), **kwargs)
        self.unit_events.append(ev)
        return ev

    async def branch_names(self, ids):
        return {BRANCH: "Main Branch"}

    async def warehouse_names(self, ids):
        return {WH: "Main Store"}

    async def product_index(self, ids):
        return {PART: ("SPK-1", "Spark Plug")}

    async def unit_model_names(self, ids):
        return {self._unit.id: "TVS HLX 125"}


def _unit(status=L.ASSEMBLED):
    return SimpleNamespace(
        id=uuid.uuid4(), chassis_number="CHASSIS-123", engine_number="ENGINE-999",
        status=status, branch_id=BRANCH, customer_id=None, reserved_ref=None,
        hold_reason=None, version=0,
    )


def _make(on_hand="10", unit_status=L.ASSEMBLED):
    unit = _unit(unit_status)
    inv_repo = FakeInventoryRepo()
    if on_hand is not None:
        inv_repo.seed(PART, WH, on_hand=on_hand, tenant_id=TENANT)
    audit = FakeAuditRepo()
    inventory = InventoryService(inv_repo, FakeLookup({PART}), FakeLookup({WH}), audit)
    repo = FakeBikeIssueRepo(unit)
    svc = BikeIssueService(repo, inventory, audit)
    return svc, repo, inv_repo, audit, unit


async def _open(svc, repo, *, lines=None, problem="Front brake seized"):
    payload = BikeIssueCreate(unit_id=repo._unit.id, problem_description=problem, lines=lines or [])
    return await svc.open(tenant_id=TENANT, user_id=USER, payload=payload)


# ------------------------------------------------------------------------- #
async def test_open_puts_bike_on_hold_and_snapshots_identity_from_unit():
    svc, repo, _inv, _audit, unit = _make()
    out = await _open(svc, repo)

    assert out.status == S.OPEN
    # Chassis / engine come from the UNIT record, not retyped by the caller.
    assert out.chassis_number == "CHASSIS-123"
    assert out.engine_number == "ENGINE-999"
    # The bike is held so it can't be sold mid-repair, with the issue as the reason.
    assert unit.status == L.ON_HOLD
    assert "Front brake seized" in unit.hold_reason
    assert out.prior_status == L.ASSEMBLED
    assert any(e.to_status == L.ON_HOLD for e in repo.unit_events)


async def test_resolve_consumes_part_once_via_inventory_marked_repair_not_sale():
    line = RepairLineIn(product_id=PART, warehouse_id=WH, quantity=3)
    svc, repo, inv_repo, _audit, _unit = _make(on_hand="10")
    out = await _open(svc, repo, lines=[line])

    resolved = await svc.resolve(
        tenant_id=TENANT, user_id=USER, issue_id=out.id, payload=BikeIssueResolve()
    )

    # qty_on_hand down exactly once (10 -> 7), one issue movement, tagged bike_repair.
    row = inv_repo._rows[(PART, WH)]
    assert row.qty_on_hand == Decimal("7")
    issue_movements = [m for m in inv_repo.movements if m.movement_type == "issue"]
    assert len(issue_movements) == 1
    mv = issue_movements[0]
    assert mv.quantity == Decimal("-3")
    assert mv.reference_type == REPAIR_REF == "bike_repair"
    # It is provably NOT a sale: sales tag movements 'sales_delivery' and write an invoice.
    assert mv.reference_type != "sales_delivery"
    assert resolved.status == S.RESOLVED
    assert resolved.lines[0].consumed is True


async def test_resolve_returns_bike_to_prior_sellable_status():
    svc, repo, _inv, _audit, unit = _make()
    out = await _open(svc, repo, lines=[RepairLineIn(product_id=PART, warehouse_id=WH, quantity=1)])
    assert unit.status == L.ON_HOLD

    await svc.resolve(tenant_id=TENANT, user_id=USER, issue_id=out.id, payload=BikeIssueResolve())

    assert unit.status == L.ASSEMBLED       # restored to what it was before the repair
    assert unit.hold_reason is None
    assert any(e.from_status == L.ON_HOLD and e.to_status == L.ASSEMBLED for e in repo.unit_events)


async def test_resolve_insufficient_stock_rejected_no_negative_no_state_change():
    svc, repo, inv_repo, _audit, unit = _make(on_hand="2")
    out = await _open(svc, repo, lines=[RepairLineIn(product_id=PART, warehouse_id=WH, quantity=5)])

    with pytest.raises(BusinessRuleError):
        await svc.resolve(tenant_id=TENANT, user_id=USER, issue_id=out.id, payload=BikeIssueResolve())

    # No negative stock, no consumption, issue stays open, bike stays on hold.
    assert inv_repo._rows[(PART, WH)].qty_on_hand == Decimal("2")
    assert not [m for m in inv_repo.movements if m.movement_type == "issue"]
    stored = repo._issues[out.id]
    assert stored.status == S.OPEN
    assert unit.status == L.ON_HOLD


@pytest.mark.parametrize("bad_status", [L.SOLD, L.RESERVED, L.ON_HOLD])
async def test_cannot_open_repair_on_non_sellable_unit(bad_status):
    svc, repo, _inv, _audit, _unit = _make(unit_status=bad_status)
    with pytest.raises(BusinessRuleError):
        await svc.open(
            tenant_id=TENANT, user_id=USER,
            payload=BikeIssueCreate(unit_id=repo._unit.id, problem_description="x"),
        )


async def test_open_unknown_unit_raises_not_found():
    svc, repo, _inv, _audit, _unit = _make()
    with pytest.raises(NotFoundError):
        await svc.open(
            tenant_id=TENANT, user_id=USER,
            payload=BikeIssueCreate(unit_id=uuid.uuid4(), problem_description="x"),
        )


async def test_resolve_with_no_parts_just_releases_the_bike():
    svc, repo, inv_repo, _audit, unit = _make()
    out = await _open(svc, repo)  # no lines

    resolved = await svc.resolve(tenant_id=TENANT, user_id=USER, issue_id=out.id, payload=BikeIssueResolve())

    assert resolved.status == S.RESOLVED
    assert unit.status == L.ASSEMBLED
    assert not inv_repo.movements  # nothing consumed


def test_bike_issues_module_never_writes_qty_on_hand_directly():
    """Grep guard: the ONE stock write path is InventoryService. No file in the
    bike_issues package may ASSIGN qty_on_hand (mentioning it in a comment is fine)."""
    import re

    # qty_on_hand on the left of an assignment (=, +=, -=), but not a comparison (==).
    assign = re.compile(r"qty_on_hand\s*(?:\+=|-=|=)(?!=)")
    pkg = Path(__file__).resolve().parents[2] / "app" / "bike_issues"
    offenders = [
        p.name for p in pkg.rglob("*.py")
        if assign.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"bike_issues must not write qty_on_hand: {offenders}"
