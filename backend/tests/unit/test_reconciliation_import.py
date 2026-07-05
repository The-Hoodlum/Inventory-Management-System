"""Unit tests for the reconciliation gate: the ImportPlan delta helper + target registration."""
from __future__ import annotations

from decimal import Decimal

from app.imports.domain.atomic import ImportPlan, ReconLine
from app.imports.domain.registry import get_importer
from app.imports.targets import stock_reconciliation  # noqa: F401  (registers the target)


def test_has_deltas_is_true_only_when_a_line_differs():
    clean = ImportPlan(reconciliation=[
        ReconLine(product="A", warehouse="W", computed=Decimal(10), actual=Decimal(10), delta=Decimal(0)),
        ReconLine(product="B", warehouse="W", computed=Decimal(5), actual=Decimal(5), delta=Decimal(0)),
    ])
    assert clean.has_deltas is False

    dirty = ImportPlan(reconciliation=[
        ReconLine(product="A", warehouse="W", computed=Decimal(10), actual=Decimal(10), delta=Decimal(0)),
        ReconLine(product="B", warehouse="W", computed=Decimal(5), actual=Decimal(3), delta=Decimal(-2)),
    ])
    assert dirty.has_deltas is True


def test_empty_plan_has_no_deltas():
    assert ImportPlan().has_deltas is False


def test_importer_is_registered_and_atomic():
    imp = get_importer("stock_reconciliation")
    assert getattr(imp, "atomic", False) is True
    assert imp.key_field == "product"
    required = {f.name for f in imp.fields if f.required}
    assert required == {"product", "warehouse", "actual_qty"}
