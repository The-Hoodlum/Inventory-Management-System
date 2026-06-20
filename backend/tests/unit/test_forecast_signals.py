"""Unit tests for the forecast signal pipeline (intelligence extension seam)."""
from __future__ import annotations

from decimal import Decimal

from app.forecast.domain.methods import package_result
from app.forecast.domain.models import ForecastMethod
from app.forecast.domain.signals import (
    AdjustedForecast,
    ForecastSignal,
    SignalAdjustment,
    SignalContext,
    SignalPipeline,
)

D = Decimal


def _base(daily: str):
    # a one-element series whose mean is `daily` keeps daily_demand exact
    return package_result([D(daily)], D(daily), ForecastMethod.MOVING_AVERAGE)


class _ScaleSignal(ForecastSignal):
    def __init__(self, key, category, factor, risk):
        self.key = key
        self.category = category
        self._factor = D(factor)
        self._risk = D(risk)

    def evaluate(self, ctx: SignalContext) -> SignalAdjustment | None:
        return SignalAdjustment(
            source=self.key, category=self.category,
            demand_factor=self._factor, risk_delta=self._risk, reason="test",
        )


class _AbstainSignal(ForecastSignal):
    key = "abstain"
    category = "supplier"

    def evaluate(self, ctx: SignalContext) -> SignalAdjustment | None:
        return None


def test_empty_pipeline_is_passthrough():
    base = _base("10")
    out = SignalPipeline().apply(SignalContext(base=base))
    assert isinstance(out, AdjustedForecast)
    assert out.adjusted_daily_demand == D("10.0000")
    assert out.risk_score == D("0.0000")
    assert out.adjustments == []


def test_single_signal_scales_demand_and_adds_risk():
    base = _base("10")
    pipe = SignalPipeline([_ScaleSignal("port", "port", "1.2", "0.3")])
    out = pipe.apply(SignalContext(base=base))
    assert out.adjusted_daily_demand == D("12.0000")
    assert out.risk_score == D("0.3000")
    assert len(out.adjustments) == 1
    assert out.adjustments[0].category == "port"


def test_multiple_signals_compose_factors_and_sum_risk():
    base = _base("10")
    pipe = SignalPipeline([
        _ScaleSignal("a", "freight", "1.1", "0.2"),
        _ScaleSignal("b", "commodity", "2.0", "0.3"),
    ])
    out = pipe.apply(SignalContext(base=base))
    assert out.adjusted_daily_demand == D("22.0000")  # 10 * 1.1 * 2.0
    assert out.risk_score == D("0.5000")


def test_risk_score_is_clamped_to_one():
    base = _base("5")
    pipe = SignalPipeline([
        _ScaleSignal("a", "geopolitical", "1.0", "0.7"),
        _ScaleSignal("b", "trade", "1.0", "0.8"),
    ])
    out = pipe.apply(SignalContext(base=base))
    assert out.risk_score == D("1.0000")


def test_abstaining_signal_is_skipped():
    base = _base("10")
    pipe = SignalPipeline([_AbstainSignal()])
    out = pipe.apply(SignalContext(base=base))
    assert out.adjusted_daily_demand == D("10.0000")
    assert out.adjustments == []
