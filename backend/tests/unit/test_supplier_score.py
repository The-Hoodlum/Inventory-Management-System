"""Unit tests for the supplier scorecard domain and the refresh service."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.intelligence.domain.supplier_risk import SupplierMetrics, supplier_risk
from app.intelligence.domain.supplier_score import (
    SupplierHistory,
    build_scorecard,
    grade_for,
)
from app.intelligence.service import IntelligenceService

D = Decimal


def _metrics(on_time=0.8, avg=30, stdev=6, fill=0.95, received=10):
    return SupplierMetrics(
        on_time_rate=on_time, avg_lead_time_days=avg, lead_time_stdev_days=stdev,
        fill_rate=fill, received_po_count=received,
    )


def _history(po=12, received=10, spend="50000", last=None):
    return SupplierHistory(
        po_count=po, received_po_count=received, total_spend=D(spend),
        last_order_at=last or dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
    )


# -------------------------------- grade_for -------------------------------- #
def test_grade_for_bands():
    assert grade_for(D("0.05")) == "A"
    assert grade_for(D("0.20")) == "B"
    assert grade_for(D("0.40")) == "C"
    assert grade_for(D("0.60")) == "D"
    assert grade_for(D("0.80")) == "F"


# ------------------------------ build_scorecard ----------------------------- #
def test_scorecard_without_intelligence_reflects_performance_only():
    m = _metrics()
    card = build_scorecard(
        supplier_name="Acme", metrics=m, history=_history(), internal=supplier_risk(m),
        intelligence_risk=D("0"), intel_drivers=[],
    )
    # internal risk = 0.2*.4 + 0.05*.3 + 0.2*.3 = 0.1550 ; no intel -> overall == perf
    assert card.performance_risk == D("0.1550")
    assert card.intelligence_risk == D("0.0000")
    assert card.risk_score == D("0.1550")
    assert card.reliability == D("0.8450")
    assert card.grade == "B"
    assert card.lead_time_accuracy == D("0.8000")  # 1 - 6/30
    assert card.delivery_performance == D("0.8000")
    assert card.fill_rate == D("0.9500")


def test_scorecard_blends_intelligence_risk():
    m = _metrics()
    card = build_scorecard(
        supplier_name="Acme", metrics=m, history=_history(), internal=supplier_risk(m),
        intelligence_risk=D("0.4"), intel_drivers=["Tariff on CN"],
    )
    # blended = 1 - (1-0.155)(1-0.4) = 1 - 0.507 = 0.4930
    assert card.intelligence_risk == D("0.4000")
    assert card.risk_score == D("0.4930")
    assert card.grade == "D"
    assert "Tariff on CN" in card.drivers


def test_scorecard_carries_purchase_history():
    m = _metrics()
    card = build_scorecard(
        supplier_name="Acme", metrics=m,
        history=_history(po=20, received=18, spend="125000.50"),
        internal=supplier_risk(m),
    )
    assert card.po_count == 20
    assert card.received_po_count == 18
    assert card.total_spend == D("125000.5000")
    assert card.last_order_at is not None


# ------------------------------ refresh service ----------------------------- #
def _signal_row(category, scope_type, scope_key, severity, headline):
    return SimpleNamespace(
        category=category, scope_type=scope_type, scope_key=scope_key,
        severity=D(severity), demand_factor=D("1"), confidence=D("0.9"), headline=headline,
    )


class _FakeScoreRepo:
    def __init__(self, inputs, signals):
        self._inputs = inputs
        self._signals = signals
        self.saved: list = []

    async def supplier_score_inputs(self):
        return list(self._inputs)

    async def active(self):
        return list(self._signals)

    async def supplier_country_map(self):
        return {}

    async def save_supplier_score(self, **fields):
        row = SimpleNamespace(id=uuid.uuid4(), computed_at=dt.datetime.now(dt.timezone.utc), **fields)
        self.saved.append(row)
        return row


async def test_refresh_supplier_scores_blends_country_signal_and_persists(fake_audit_repo):
    sid = uuid.uuid4()
    repo = _FakeScoreRepo(
        inputs=[(sid, "Acme Co", "CN", _metrics(), _history())],
        # a country-scoped freight signal for CN should reach the CN supplier
        signals=[_signal_row("freight", "country", "CN", "0.4", "Freight ex-CN +40%")],
    )
    svc = IntelligenceService(repo, fake_audit_repo)

    resp = await svc.refresh_supplier_scores(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    assert resp.scored == 1
    saved = repo.saved[0]
    assert saved.supplier_id == sid
    assert saved.performance_risk == D("0.1550")
    assert saved.intelligence_risk == D("0.4000")   # CN freight signal influenced the score
    assert saved.risk_score == D("0.4930")
    assert saved.grade == "D"
    assert any("Freight" in d for d in saved.drivers)
    assert any(e["action"] == "supplier.score.refresh" for e in fake_audit_repo.entries)


async def test_refresh_supplier_scores_without_signals_is_performance_only(fake_audit_repo):
    sid = uuid.uuid4()
    repo = _FakeScoreRepo(inputs=[(sid, "Acme Co", "CN", _metrics(), _history())], signals=[])
    svc = IntelligenceService(repo, fake_audit_repo)

    await svc.refresh_supplier_scores(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    saved = repo.saved[0]
    assert saved.intelligence_risk == D("0.0000")
    assert saved.risk_score == D("0.1550")
    assert saved.grade == "B"
