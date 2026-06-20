"""Forecast service: generate, persist, track accuracy, and summarise forecasts.

Orchestration only — the maths live in ``app.forecast.domain``. Each generated
forecast runs through the (currently empty) signal pipeline, so when intelligence
signals are added later they automatically flow into stored forecasts, the
dashboard, and reorder, with no change here.

Demand history comes from the canonical ``DemandRepository.daily_series`` (the
single source of truth, fed by the issue rollup and any future import source).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from app.core.exceptions import NotFoundError
from app.forecast.domain.accuracy import forecast_accuracy
from app.forecast.domain.methods import build_series
from app.forecast.domain.models import ForecastParams
from app.forecast.domain.patterns import analyze
from app.forecast.domain.providers import (
    available_providers,
    default_provider_key,
    get_provider,
)
from app.forecast.domain.signals import SignalContext, default_pipeline
from app.forecast.schemas import (
    DemandPatternResponse,
    ForecastAccuracyResponse,
    ForecastOut,
    ForecastRunResponse,
    ForecastSummaryResponse,
    ProviderOut,
)
from app.intelligence.signals import build_snapshot

# Selection mode (not a registry provider): detect the best method per product.
AUTO_METHOD = "auto"

_Q4 = Decimal("0.0001")


class ForecastService:
    def __init__(self, forecast_repo, demand_repo, audit_repo, intelligence_repo=None) -> None:
        self.repo = forecast_repo
        self.demand = demand_repo
        self.audit = audit_repo
        # Optional: makes forecasts risk-aware (adjusted demand + risk score).
        self.intelligence = intelligence_repo

    # ------------------------------ providers ------------------------------ #
    @staticmethod
    def providers() -> list[ProviderOut]:
        items = [ProviderOut(key=p.key, label=p.label) for p in available_providers()]
        # 'auto' is a selection mode, not a registered provider — surfaced so the UI
        # can offer per-product method detection.
        items.append(ProviderOut(key=AUTO_METHOD, label="Auto (detect per product)"))
        return items

    # -------------------------------- run ---------------------------------- #
    async def run(self, *, tenant_id, user_id, req, ip: str | None = None) -> ForecastRunResponse:
        auto = (req.method or "").lower() == AUTO_METHOD
        # In auto mode the provider is chosen per product from its detected pattern;
        # otherwise one provider is resolved up front for the whole run.
        provider = None if auto else get_provider(req.method or default_provider_key())
        selected_method = AUTO_METHOD if auto else provider.key
        params = ForecastParams(
            window_days=req.window_days,
            horizon_days=req.horizon_days,
            ma_window=req.ma_window,
            alpha=req.alpha,
            croston_alpha=req.croston_alpha,
            seasonal_period=req.seasonal_period,
        )
        end_day = req.as_of or dt.date.today()
        start_day = end_day - dt.timedelta(days=req.window_days - 1)
        forecast_date = end_day + dt.timedelta(days=1)  # first day the forecast applies to
        pipeline = default_pipeline()

        if req.product_id is not None:
            targets = [req.product_id]
        else:
            targets = await self.repo.list_active_product_ids()

        # Risk overlay: attach an intelligence snapshot so the registered
        # IntelligenceForecastSignal can adjust demand + risk per SKU's supplier.
        snapshot = None
        supplier_map: dict = {}
        if self.intelligence is not None and targets:
            rows = await self.intelligence.active()
            if rows:
                snapshot = build_snapshot(rows, await self.intelligence.supplier_country_map())
                supplier_map = await self.repo.product_supplier_map(targets)

        saved_rows = []
        for product_id in targets:
            points = await self.demand.daily_series(
                product_id=product_id,
                warehouse_id=req.warehouse_id,
                start_date=start_day,
                end_date=end_day,
            )
            series = build_series(points, end_day=end_day, window_days=req.window_days)
            chosen = get_provider(analyze(series).suggested_method) if auto else provider
            base = chosen.generate(series, params)
            adjusted = pipeline.apply(
                SignalContext(
                    base=base,
                    product_id=product_id,
                    warehouse_id=req.warehouse_id,
                    supplier_id=supplier_map.get(product_id),
                    as_of=end_day,
                    extra={"intelligence": snapshot} if snapshot is not None else {},
                )
            )
            saved = await self.repo.save(
                tenant_id=tenant_id,
                product_id=product_id,
                warehouse_id=req.warehouse_id,
                method=base.method,
                window_days=req.window_days,
                horizon_days=req.horizon_days,
                forecast_date=forecast_date,
                daily_demand=base.daily_demand,
                adjusted_daily_demand=adjusted.adjusted_daily_demand,
                std_dev_daily=base.std_dev_daily,
                confidence=base.confidence,
                risk_score=adjusted.risk_score,
                observations=base.observations,
                days_with_demand=base.days_with_demand,
                total_demand=base.total_demand,
                params={
                    "ma_window": req.ma_window,
                    "alpha": str(req.alpha),
                    "croston_alpha": str(req.croston_alpha),
                    "seasonal_period": req.seasonal_period,
                    "selected": selected_method,
                },
                generated_by=user_id,
            )
            saved_rows.append(saved)

        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="forecast.run",
            entity_type="demand_forecast",
            entity_id=None,
            changes={
                "method": selected_method,
                "warehouse_id": str(req.warehouse_id),
                "count": len(saved_rows),
                "window_days": req.window_days,
                "horizon_days": req.horizon_days,
            },
            ip_address=ip,
        )
        return ForecastRunResponse(
            method=selected_method,
            warehouse_id=req.warehouse_id,
            generated=len(saved_rows),
            forecasts=[ForecastOut.model_validate(r) for r in saved_rows],
        )

    # ------------------------------- reads --------------------------------- #
    async def list(self, **kwargs) -> tuple[list, int]:
        return await self.repo.list(**kwargs)

    # ------------------------------ analyze -------------------------------- #
    async def analyze_demand(
        self, *, product_id, warehouse_id, window_days: int = 90, as_of=None
    ) -> DemandPatternResponse:
        """Measure a (product, warehouse) demand series and return its detected
        pattern + suggested demand_type / method. Read-only; persists nothing."""
        end_day = as_of or dt.date.today()
        start_day = end_day - dt.timedelta(days=window_days - 1)
        points = await self.demand.daily_series(
            product_id=product_id,
            warehouse_id=warehouse_id,
            start_date=start_day,
            end_date=end_day,
        )
        series = build_series(points, end_day=end_day, window_days=window_days)
        p = analyze(series)
        return DemandPatternResponse(
            product_id=product_id,
            warehouse_id=warehouse_id,
            window_days=window_days,
            as_of=end_day,
            observations=p.n,
            days_with_demand=p.days_with_demand,
            adi=p.adi,
            cv_squared=p.cv_squared,
            classification=p.classification,
            trend_direction=p.trend_direction,
            trend_slope=p.trend_slope,
            trend_strength=p.trend_strength,
            seasonal=p.seasonal,
            seasonal_period=p.seasonal_period,
            seasonal_strength=p.seasonal_strength,
            suggested_demand_type=p.suggested_demand_type,
            suggested_method=p.suggested_method,
            drivers=p.drivers,
        )

    # ------------------------------ accuracy ------------------------------- #
    async def accuracy(self, forecast_id: uuid.UUID) -> ForecastAccuracyResponse:
        f = await self.repo.get(forecast_id)
        if f is None:
            raise NotFoundError("Forecast not found")

        today = dt.date.today()
        last_day = f.forecast_date + dt.timedelta(days=f.horizon_days - 1)
        end = min(last_day, today)

        if end < f.forecast_date:
            # Forecast horizon hasn't started yet — nothing to compare.
            return self._accuracy_response(f, evaluated_days=0, acc=None)

        elapsed = (end - f.forecast_date).days + 1
        points = await self.demand.daily_series(
            product_id=f.product_id,
            warehouse_id=f.warehouse_id,
            start_date=f.forecast_date,
            end_date=end,
        )
        actuals = build_series(points, end_day=end, window_days=elapsed)
        predicted = Decimal(f.adjusted_daily_demand)
        acc = forecast_accuracy([(predicted, a) for a in actuals])
        return self._accuracy_response(f, evaluated_days=acc.n, acc=acc)

    @staticmethod
    def _accuracy_response(f, *, evaluated_days: int, acc) -> ForecastAccuracyResponse:
        return ForecastAccuracyResponse(
            forecast_id=f.id,
            product_id=f.product_id,
            warehouse_id=f.warehouse_id,
            method=f.method,
            forecast_date=f.forecast_date,
            horizon_days=f.horizon_days,
            evaluated_days=evaluated_days,
            mae=acc.mae if acc else None,
            bias=acc.bias if acc else None,
            rmse=acc.rmse if acc else None,
            mape=acc.mape if acc else None,
            mape_points=acc.mape_points if acc else 0,
        )

    # ------------------------------ summary -------------------------------- #
    async def summary(self) -> ForecastSummaryResponse:
        latest = await self.repo.latest_per_pair()
        total = await self.repo.count_all()
        now = dt.datetime.now(dt.UTC)

        if not latest:
            return ForecastSummaryResponse(
                total_forecasts=total,
                pairs_forecasted=0,
                avg_confidence=None,
                avg_risk_score=None,
                high_risk_count=0,
                by_method={},
                recent=[],
                generated_at=now,
            )

        n = len(latest)
        avg_conf = (sum((Decimal(f.confidence) for f in latest), Decimal(0)) / n).quantize(
            _Q4, rounding=ROUND_HALF_UP
        )
        avg_risk = (sum((Decimal(f.risk_score) for f in latest), Decimal(0)) / n).quantize(
            _Q4, rounding=ROUND_HALF_UP
        )
        high_risk = sum(1 for f in latest if Decimal(f.risk_score) >= Decimal("0.5"))
        by_method = dict(Counter(f.method for f in latest))
        recent = sorted(latest, key=lambda f: f.generated_at, reverse=True)[:10]

        return ForecastSummaryResponse(
            total_forecasts=total,
            pairs_forecasted=n,
            avg_confidence=avg_conf,
            avg_risk_score=avg_risk,
            high_risk_count=high_risk,
            by_method=by_method,
            recent=[ForecastOut.model_validate(f) for f in recent],
            generated_at=now,
        )
