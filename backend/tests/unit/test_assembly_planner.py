"""Assembly-planner tests.

The core guarantees: deterministic from CURRENT counts (no demand read), thin+buildable
combos become assemble recommendations capped by unassembled units, thin combos with
nothing to build from surface as gaps (not recommendations), and counts respect branch
scope.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from app.assembly.domain import planner as P
from app.assembly.repository import ComboCount
from app.assembly.service import AssemblyPlannerService
from tests.conftest import FakeAuditRepo

TENANT = uuid.uuid4()
USER = uuid.uuid4()
HLX150 = uuid.uuid4()
BLUE = uuid.uuid4()
RED = uuid.uuid4()
BRANCH_A = uuid.uuid4()
BRANCH_B = uuid.uuid4()


# ----------------------------- pure domain ------------------------------- #
def test_thin_and_buildable_recommends_capped_by_unassembled():
    # 1 assembled + 3 unassembled, threshold 1, high target -> cap binds at 3.
    out = P.plan_combo(P.ComboInput(assembled=1, unassembled=3, target=10, threshold=1))
    assert out.is_recommendation and not out.is_gap
    assert out.recommended_qty == 3  # never more than unassembled available


def test_thin_and_buildable_recommends_toward_target():
    out = P.plan_combo(P.ComboInput(assembled=1, unassembled=3, target=2, threshold=1))
    assert out.is_recommendation
    assert out.recommended_qty == 1  # min(target-assembled=1, unassembled=3)


def test_thin_but_nothing_to_build_is_a_gap_not_a_recommendation():
    out = P.plan_combo(P.ComboInput(assembled=1, unassembled=0, target=2, threshold=1))
    assert out.is_gap and not out.is_recommendation
    assert out.recommended_qty == 0


def test_above_threshold_is_not_flagged():
    out = P.plan_combo(P.ComboInput(assembled=5, unassembled=3, target=2, threshold=1))
    assert not out.is_recommendation and not out.is_gap


def test_recommended_never_exceeds_unassembled():
    for unassembled in range(0, 6):
        out = P.plan_combo(P.ComboInput(assembled=0, unassembled=unassembled, target=99, threshold=1))
        assert out.recommended_qty <= unassembled


# ------------------------------- service --------------------------------- #
class FakeAssemblyRepo:
    def __init__(self, counts, *, targets=None):
        self.session = SimpleNamespace(flush=_noop, add=lambda o: None, delete=_noop)
        self._counts = counts
        self._targets = targets or []
        self.last_branch_ids = "unset"

    async def assembly_counts(self, *, branch_ids=None, model_id=None):
        # Branch/model filtering is SQL-level in the real repo; here we just record the
        # scope the service passed through and return the seeded counts.
        self.last_branch_ids = branch_ids
        self.last_model_id = model_id
        return list(self._counts)

    async def list_targets(self):
        return self._targets

    async def model_names(self, ids):
        return {HLX150: "HLX 150"}

    async def variant_names(self, ids):
        return {}

    async def colour_names(self, ids):
        return {BLUE: "Blue", RED: "Red"}


async def _noop(*a, **k):
    return None


def _svc(counts, targets=None):
    return AssemblyPlannerService(FakeAssemblyRepo(counts, targets=targets), FakeAuditRepo())


async def test_service_splits_recommendations_and_gaps():
    counts = [
        ComboCount(HLX150, None, BLUE, assembled=1, unassembled=3),  # thin + buildable -> rec
        ComboCount(HLX150, None, RED, assembled=1, unassembled=0),   # thin + nothing  -> gap
        ComboCount(HLX150, None, None, assembled=9, unassembled=2),  # healthy         -> neither
    ]
    plan = await _svc(counts).plan(branch_ids=None)

    assert [r.colour_id for r in plan.recommendations] == [BLUE]
    assert plan.recommendations[0].recommended_qty == 1  # default target 2 - 1 assembled
    assert plan.recommendations[0].unassembled_available == 3
    assert [g.colour_id for g in plan.gaps] == [RED]
    assert plan.default_target_assembled == P.DEFAULT_TARGET_ASSEMBLED
    assert plan.default_threshold == P.DEFAULT_THRESHOLD


async def test_service_applies_per_combo_target_override():
    counts = [ComboCount(HLX150, None, BLUE, assembled=1, unassembled=3)]
    targets = [SimpleNamespace(id=uuid.uuid4(), model_id=HLX150, colour_id=BLUE, target_assembled=10, threshold=1)]
    plan = await _svc(counts, targets).plan(branch_ids=None)
    # target 10 - 1 assembled = 9, capped by 3 unassembled.
    assert plan.recommendations[0].recommended_qty == 3


async def test_plan_passes_branch_scope_through():
    repo = FakeAssemblyRepo([ComboCount(HLX150, None, BLUE, 1, 3)])
    svc = AssemblyPlannerService(repo, FakeAuditRepo())
    await svc.plan(branch_ids=[BRANCH_A])
    assert repo.last_branch_ids == [BRANCH_A]


def test_module_reads_no_sales_or_demand_data():
    """Guard the core principle: the planner counts stock only. It must not IMPORT or query
    any sales / demand / forecast source (data-access tokens, not the words in a comment)."""
    forbidden = (
        "app.demand", "app.forecast", "app.sales", "sales_daily",
        "SalesDaily", "InvoiceLine", "daily_series", "demand_aggregates",
    )
    pkg = Path(__file__).resolve().parents[2] / "app" / "assembly"
    offenders = {}
    for p in pkg.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        hits = [w for w in forbidden if w in text]
        if hits:
            offenders[p.name] = hits
    assert offenders == {}, f"assembly planner must not read demand data: {offenders}"
