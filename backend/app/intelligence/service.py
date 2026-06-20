"""Intelligence service: ingest observations, aggregate risk, and prove the feed.

Composes the providers (supplier risk = computed; freight/port/commodity/trade =
external-feed, no-op until a source is configured), persists their observations,
and exposes:
  * dashboard()        — overall risk, forecast impact, confidence, actions, drivers
  * pipeline_impact()  — runs the *registered* forecast SignalPipeline over the
                         current intelligence snapshot, demonstrating end-to-end
                         that intelligence feeds forecasting.

Importing this module registers the IntelligenceForecastSignal bridge.
"""
from __future__ import annotations

import datetime as dt
import uuid

from app.forecast.domain.methods import package_result
from app.forecast.domain.models import ForecastMethod
from decimal import Decimal

from app.core.exceptions import NotFoundError
from app.forecast.domain.signals import SignalContext, default_pipeline
from app.intelligence.domain.scoring import ScopedAdjustment, assess
from app.intelligence.domain.supplier_risk import supplier_risk
from app.intelligence.domain.supplier_score import build_scorecard
from app.intelligence.providers.base import ExternalSource, NullSource, Observation
from app.intelligence.providers.feeds import (
    CommodityIntelligenceProvider,
    FreightIntelligenceProvider,
    PortIntelligenceProvider,
    TradeIntelligenceProvider,
)
from app.intelligence.providers.supplier import SupplierRiskProvider
from app.intelligence.schemas import (
    IngestResponse,
    IntelligenceDashboardResponse,
    PipelineImpactResponse,
    SignalOut,
    SupplierScoreDetail,
    SupplierScoreOut,
    SupplierScoreRefreshResponse,
)
from app.intelligence.signals import build_snapshot, match_context  # noqa: F401 (registers the bridge)


class IntelligenceService:
    def __init__(self, repo, audit, source: ExternalSource | None = None, extra_providers=None) -> None:
        self.repo = repo
        self.audit = audit
        self.source = source or NullSource()
        # Additional providers (the enabled free/public HTTP feeds, built from
        # settings by providers.registry). Empty by default — engine unchanged.
        self._extra_providers = list(extra_providers or [])

    def _providers(self) -> list:
        return [
            SupplierRiskProvider(self.repo),
            FreightIntelligenceProvider(self.source),
            PortIntelligenceProvider(self.source),
            CommodityIntelligenceProvider(self.source),
            TradeIntelligenceProvider(self.source),
        ] + self._extra_providers

    # ------------------------------ ingest ------------------------------- #
    async def ingest(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, categories=None, ip: str | None = None
    ) -> IngestResponse:
        providers = self._providers()
        if categories:
            providers = [p for p in providers if p.category in set(categories)]

        by_category: dict[str, int] = {}
        by_source: dict[str, int] = {}
        total = 0
        for provider in providers:
            # Replace-by-source: each provider's current view supersedes its last
            # run (manual observations, source='manual', are never touched here).
            await self.repo.delete_by_source(provider.key)
            for obs in await provider.collect():
                await self.repo.add_observation(tenant_id, obs)
                by_category[obs.category] = by_category.get(obs.category, 0) + 1
                by_source[obs.source] = by_source.get(obs.source, 0) + 1
                total += 1

        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="intelligence.ingest",
            entity_type="intelligence_signal", entity_id=None,
            changes={"ingested": total, "by_category": by_category, "by_source": by_source},
            ip_address=ip,
        )
        return IngestResponse(ingested=total, by_category=by_category, by_source=by_source)

    async def record_manual(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, req, ip: str | None = None
    ) -> SignalOut:
        obs = Observation(
            category=req.category, scope_type=req.scope_type, scope_key=req.scope_key,
            severity=req.severity, demand_factor=req.demand_factor, confidence=req.confidence,
            headline=req.headline, source="manual", value=req.value, unit=req.unit,
            trend=req.trend, expires_at=req.expires_at, detail=req.detail,
        )
        row = await self.repo.add_observation(tenant_id, obs)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="intelligence.manual",
            entity_type="intelligence_signal", entity_id=row.id,
            changes={"category": obs.category, "scope": f"{obs.scope_type}:{obs.scope_key}",
                     "severity": str(obs.severity), "headline": obs.headline},
            ip_address=ip,
        )
        return SignalOut.model_validate(row)

    # ------------------------------- reads ------------------------------- #
    async def list(self, **kwargs):
        return await self.repo.list(**kwargs)

    async def dashboard(self) -> IntelligenceDashboardResponse:
        rows = await self.repo.active()
        adjustments = [
            ScopedAdjustment(
                category=r.category, severity=r.severity, demand_factor=r.demand_factor,
                confidence=r.confidence, headline=r.headline,
            )
            for r in rows
        ]
        a = assess(adjustments)
        return IntelligenceDashboardResponse(
            risk_score=a.risk_score,
            forecast_impact=a.demand_factor,
            confidence=a.confidence,
            active_signals=len(rows),
            by_category=a.by_category,
            recommended_actions=a.actions,
            drivers=a.drivers,
            generated_at=dt.datetime.now(dt.timezone.utc),
        )

    async def pipeline_impact(
        self, *, base_daily_demand, supplier_id: uuid.UUID | None = None
    ) -> PipelineImpactResponse:
        rows = await self.repo.active()
        snap = build_snapshot(rows, await self.repo.supplier_country_map())
        base = package_result([base_daily_demand], base_daily_demand, ForecastMethod.MOVING_AVERAGE)
        ctx = SignalContext(base=base, supplier_id=supplier_id, extra={"intelligence": snap})
        out = default_pipeline().apply(ctx)
        return PipelineImpactResponse(
            supplier_id=supplier_id,
            base_daily_demand=base.daily_demand,
            adjusted_daily_demand=out.adjusted_daily_demand,
            risk_score=out.risk_score,
            applied=[adj.reason for adj in out.adjustments],
        )

    # --------------------------- supplier scores --------------------------- #
    async def refresh_supplier_scores(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, ip: str | None = None
    ) -> SupplierScoreRefreshResponse:
        """Recompute every supplier's scorecard from PO history and blend in
        active supplier/country intelligence (so signals influence the score).
        Persists one row per supplier (history retained for trend)."""
        inputs = await self.repo.supplier_score_inputs()
        snapshot = build_snapshot(await self.repo.active(), await self.repo.supplier_country_map())

        scored = 0
        for sid, name, country, metrics, history in inputs:
            internal = supplier_risk(metrics)
            # supplier-specific intelligence only (no global macro) influences the score
            matched = match_context(
                snapshot, sid, origin_country=country, include_global=False
            )
            if matched:
                assessment = assess(matched)
                intel_risk, intel_drivers = assessment.risk_score, assessment.drivers
            else:
                intel_risk, intel_drivers = Decimal("0"), []

            card = build_scorecard(
                supplier_name=name, metrics=metrics, history=history,
                internal=internal, intelligence_risk=intel_risk, intel_drivers=intel_drivers,
            )
            await self.repo.save_supplier_score(
                tenant_id=tenant_id, supplier_id=sid, supplier_name=card.supplier_name,
                on_time_rate=card.on_time_rate, avg_lead_time_days=card.avg_lead_time_days,
                lead_time_stdev_days=card.lead_time_stdev_days,
                lead_time_accuracy=card.lead_time_accuracy, fill_rate=card.fill_rate,
                delivery_performance=card.delivery_performance, reliability=card.reliability,
                performance_risk=card.performance_risk, intelligence_risk=card.intelligence_risk,
                risk_score=card.risk_score, grade=card.grade, po_count=card.po_count,
                received_po_count=card.received_po_count, total_spend=card.total_spend,
                last_order_at=card.last_order_at, drivers=card.drivers or None,
            )
            scored += 1

        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="supplier.score.refresh",
            entity_type="supplier_score", entity_id=None,
            changes={"scored": scored}, ip_address=ip,
        )
        return SupplierScoreRefreshResponse(
            scored=scored, generated_at=dt.datetime.now(dt.timezone.utc)
        )

    async def supplier_scores(self) -> list:
        return await self.repo.latest_supplier_scores()

    async def supplier_score_detail(self, supplier_id: uuid.UUID) -> SupplierScoreDetail:
        history = await self.repo.supplier_score_history(supplier_id)
        if not history:
            raise NotFoundError("No score computed for this supplier yet")
        return SupplierScoreDetail(
            latest=SupplierScoreOut.model_validate(history[0]),
            history=[SupplierScoreOut.model_validate(h) for h in history],
        )
