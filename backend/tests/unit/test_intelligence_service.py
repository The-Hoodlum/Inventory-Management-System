"""Unit tests for IntelligenceService using in-memory fakes (no database).

Includes a test proving that ingested intelligence flows through the *registered*
forecast SignalPipeline (the seam built in Phase D).
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.intelligence.domain.supplier_risk import SupplierMetrics
from app.intelligence.schemas import ManualSignalRequest
from app.intelligence.service import IntelligenceService

D = Decimal


class FakeIntelRepo:
    def __init__(self, metrics=None, country_map=None):
        self.rows: list = []
        self._metrics = metrics or []
        self._country = country_map or {}

    async def supplier_metrics(self):
        return list(self._metrics)

    async def supplier_country_map(self):
        return dict(self._country)

    async def add_observation(self, tenant_id, obs):
        row = SimpleNamespace(
            id=uuid.uuid4(), tenant_id=tenant_id,
            category=obs.category, scope_type=obs.scope_type, scope_key=obs.scope_key,
            severity=obs.severity, demand_factor=obs.demand_factor, confidence=obs.confidence,
            headline=obs.headline, value=obs.value, unit=obs.unit, trend=obs.trend,
            source=obs.source, observed_at=dt.datetime.now(dt.UTC),
            expires_at=obs.expires_at, detail=obs.detail,
        )
        self.rows.append(row)
        return row

    async def delete_by_source(self, source):
        self.rows = [r for r in self.rows if r.source != source]

    async def active(self):
        return list(self.rows)

    async def list(self, **kwargs):
        return list(self.rows), len(self.rows)


def _metrics(sid, name, country):
    # poor on-time + volatile lead time -> non-zero risk
    return (sid, name, country, SupplierMetrics(
        on_time_rate=0.5, avg_lead_time_days=30, lead_time_stdev_days=15,
        fill_rate=0.9, received_po_count=10,
    ))


async def test_ingest_persists_supplier_risk_only_without_external_source(fake_audit_repo):
    sid = uuid.uuid4()
    repo = FakeIntelRepo(metrics=[_metrics(sid, "Acme Co", "CN")])
    svc = IntelligenceService(repo, fake_audit_repo)

    resp = await svc.ingest(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    # supplier risk is computed; freight/port/commodity/trade have no source -> nothing
    assert resp.ingested == 1
    assert resp.by_category == {"supplier": 1}
    assert resp.by_source == {"supplier_risk": 1}
    assert repo.rows[0].scope_type == "supplier"
    assert repo.rows[0].scope_key == str(sid)
    assert any(e["action"] == "intelligence.ingest" for e in fake_audit_repo.entries)


async def test_ingest_is_idempotent_per_source(fake_audit_repo):
    sid = uuid.uuid4()
    repo = FakeIntelRepo(metrics=[_metrics(sid, "Acme Co", "CN")])
    svc = IntelligenceService(repo, fake_audit_repo)
    await svc.ingest(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    await svc.ingest(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    # replace-by-source: still one supplier_risk row, not two
    assert len([r for r in repo.rows if r.source == "supplier_risk"]) == 1


async def test_record_manual_stores_observation(fake_audit_repo):
    repo = FakeIntelRepo()
    svc = IntelligenceService(repo, fake_audit_repo)
    out = await svc.record_manual(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=ManualSignalRequest(category="geopolitical", scope_type="global",
                                severity=D("0.3"), demand_factor=D("1.2"),
                                headline="Regional strike risk"),
    )
    assert out.source == "manual"
    assert out.category == "geopolitical"
    assert repo.rows[0].headline == "Regional strike risk"


async def test_dashboard_aggregates_active_signals(fake_audit_repo):
    sid = uuid.uuid4()
    repo = FakeIntelRepo(metrics=[_metrics(sid, "Acme Co", "CN")])
    svc = IntelligenceService(repo, fake_audit_repo)
    await svc.ingest(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    dash = await svc.dashboard()
    assert dash.active_signals == 1
    assert dash.risk_score > D("0")
    assert "supplier" in dash.by_category
    assert any("Supplier reliability" in a for a in dash.recommended_actions)


async def test_pipeline_impact_feeds_registered_signal_pipeline(fake_audit_repo):
    # A global manual signal (demand_factor 1.2, risk 0.3) must flow through the
    # registered forecast SignalPipeline and adjust a base demand of 100 -> 120.
    repo = FakeIntelRepo()
    svc = IntelligenceService(repo, fake_audit_repo)
    await svc.record_manual(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=ManualSignalRequest(category="geopolitical", scope_type="global",
                                severity=D("0.3"), demand_factor=D("1.2"),
                                headline="Global disruption"),
    )

    impact = await svc.pipeline_impact(base_daily_demand=D("100"), supplier_id=None)
    assert impact.base_daily_demand == D("100.0000")
    assert impact.adjusted_daily_demand == D("120.0000")  # 100 * 1.2 via the pipeline
    assert impact.risk_score == D("0.3000")
    assert impact.applied  # the intelligence signal's reason was applied


async def test_pipeline_impact_matches_supplier_scoped_signal(fake_audit_repo):
    sid = uuid.uuid4()
    repo = FakeIntelRepo(metrics=[_metrics(sid, "Acme Co", "CN")], country_map={str(sid): "CN"})
    svc = IntelligenceService(repo, fake_audit_repo)
    await svc.ingest(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    # supplier-scoped risk applies only when the context names that supplier
    impact = await svc.pipeline_impact(base_daily_demand=D("100"), supplier_id=sid)
    assert impact.risk_score > D("0")
    no_match = await svc.pipeline_impact(base_daily_demand=D("100"), supplier_id=uuid.uuid4())
    assert no_match.risk_score == D("0.0000")
