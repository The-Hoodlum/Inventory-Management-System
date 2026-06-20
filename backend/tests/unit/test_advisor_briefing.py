"""Unit tests for the deterministic advisory domain (findings, ranking, prompt)."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.advisor.domain.briefing import (
    build_context,
    finding_from_container_usage,
    findings_from_forecasts,
    findings_from_reorder,
    findings_from_signals,
    findings_from_supplier_scores,
    rank_findings,
    select_relevant,
)
from app.advisor.domain.llm import build_advisory_prompt

D = Decimal


# ------------------------------ reorder ----------------------------------- #
def test_reorder_finding_expedite_lifts_severity_and_action():
    rec = SimpleNamespace(
        product_id=uuid.uuid4(), sku="SKU1", recommended_qty=D("100"),
        risk_score=D("0.3"), expedite=True, risk_cost_impact=D("50"), risk_drivers=["port congestion"],
    )
    [f] = findings_from_reorder([rec])
    assert f.category == "reorder"
    assert f.severity == D("0.7000")          # expedite floor lifts 0.3 -> 0.7
    assert "expedite" in (f.recommended_action or "").lower()
    assert f.refs["product_id"] == str(rec.product_id)


def test_reorder_skips_zero_quantity():
    rec = SimpleNamespace(product_id=uuid.uuid4(), sku="Z", recommended_qty=D("0"), expedite=False)
    assert findings_from_reorder([rec]) == []


# ------------------------------ signals ------------------------------------ #
def test_signal_above_floor_becomes_finding_and_below_is_dropped():
    hot = SimpleNamespace(category="freight", severity=D("0.8"), headline="Freight spike", scope_type="route", scope_key="CNSHA-USLAX", trend="up", source="x")
    cold = SimpleNamespace(category="port", severity=D("0.1"), headline="minor", scope_type="port", scope_key="X", trend=None, source="x")
    findings = findings_from_signals([hot, cold])
    assert len(findings) == 1
    assert findings[0].severity == D("0.8000")
    assert "Freight spike" in findings[0].title


# -------------------------- supplier scores -------------------------------- #
def test_supplier_high_risk_and_poor_grade_surface():
    risky = SimpleNamespace(supplier_id=uuid.uuid4(), risk_score=D("0.72"), grade="C")
    fgrade = SimpleNamespace(supplier_id=uuid.uuid4(), risk_score=D("0.2"), grade="F")  # poor grade, low risk
    healthy = SimpleNamespace(supplier_id=uuid.uuid4(), risk_score=D("0.1"), grade="A")
    findings = findings_from_supplier_scores([risky, fgrade, healthy])
    assert len(findings) == 2                  # healthy A is dropped
    assert all(f.category == "supplier_risk" for f in findings)


# ----------------------------- forecasts ----------------------------------- #
def test_forecast_aggregate_finding_when_exposed():
    fcs = [
        SimpleNamespace(risk_score=D("0.7"), confidence=D("0.8")),
        SimpleNamespace(risk_score=D("0.1"), confidence=D("0.2")),
        SimpleNamespace(risk_score=D("0.1"), confidence=D("0.9")),
    ]
    [f] = findings_from_forecasts(fcs)
    assert f.category == "forecast"
    assert f.refs == {"forecasts": 3, "high_risk": 1, "low_confidence": 1}


def test_forecast_no_finding_when_all_healthy():
    fcs = [SimpleNamespace(risk_score=D("0.0"), confidence=D("0.9"))]
    assert findings_from_forecasts(fcs) == []


# ------------------------------ assembly ----------------------------------- #
def test_rank_findings_orders_by_severity_and_caps():
    from app.advisor.domain.briefing import Finding

    fs = [Finding(category="x", severity=D(s), title=str(s), detail="", refs={}) for s in ("0.2", "0.9", "0.5")]
    ranked = rank_findings(fs, limit=2)
    assert [f.severity for f in ranked] == [D("0.9"), D("0.5")]


def test_build_context_assembles_metrics_and_summary():
    rec = SimpleNamespace(product_id=uuid.uuid4(), sku="A", recommended_qty=D("10"), risk_score=D("0.6"), expedite=True)
    sig = SimpleNamespace(category="freight", severity=D("0.5"), headline="h", scope_type=None, scope_key=None, trend=None, source="s")
    ctx = build_context(reorder=[rec], signals=[sig], supplier_scores=[], forecasts=[])
    assert ctx.metrics["reorder_pending"] == 1
    assert ctx.metrics["reorder_expedite"] == 1
    assert ctx.metrics["active_signals"] == 1
    assert ctx.findings                       # at least the reorder + signal findings
    assert "pending reorder" in ctx.summary_line


# ----------------------------- container ----------------------------------- #
def test_container_finding_flags_low_fill_and_caps_severity():
    f = finding_from_container_usage(
        label="Supplier X", container_code="20GP", containers_needed=1,
        fill=D("0.3"), top_off_cartons=12,
    )
    assert f is not None and f.category == "container"
    assert f.severity == D("0.5")              # 1-0.3=0.7 capped to the 0.5 efficiency ceiling
    assert "12 more cartons" in f.detail


def test_container_finding_none_when_well_filled_or_empty():
    assert finding_from_container_usage(
        label="X", container_code="40GP", containers_needed=1, fill=D("0.9"), top_off_cartons=0
    ) is None
    assert finding_from_container_usage(
        label="X", container_code="40GP", containers_needed=0, fill=D("0.1"), top_off_cartons=0
    ) is None


# --------------------------- select_relevant ------------------------------- #
def test_select_relevant_filters_to_question_category():
    rec = SimpleNamespace(product_id=uuid.uuid4(), sku="A", recommended_qty=D("10"), risk_score=D("0.8"), expedite=False)
    sup = SimpleNamespace(supplier_id=uuid.uuid4(), risk_score=D("0.7"), grade="D")
    ctx = build_context(reorder=[rec], signals=[], supplier_scores=[sup], forecasts=[])
    rel = select_relevant(ctx, "which suppliers are risky?")
    assert rel and all(f.category == "supplier_risk" for f in rel)


def test_select_relevant_falls_back_when_no_keyword_matches():
    rec = SimpleNamespace(product_id=uuid.uuid4(), sku="A", recommended_qty=D("10"), risk_score=D("0.8"), expedite=False)
    ctx = build_context(reorder=[rec], signals=[], supplier_scores=[], forecasts=[])
    assert select_relevant(ctx, "xyzzy plugh") == ctx.findings   # nothing matched -> general ranking


# ------------------------------- prompt ------------------------------------ #
def test_advisory_prompt_is_grounded_in_findings():
    rec = SimpleNamespace(product_id=uuid.uuid4(), sku="WIDGET", recommended_qty=D("5"), risk_score=D("0.9"), expedite=False)
    ctx = build_context(reorder=[rec], signals=[], supplier_scores=[], forecasts=[])
    system, user = build_advisory_prompt(ctx, question="What should I order?")
    assert "ONLY the findings" in system
    assert "WIDGET" in user                    # the real finding is in the prompt
    assert "What should I order?" in user
