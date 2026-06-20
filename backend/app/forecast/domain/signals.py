"""Forecast signal pipeline — the extension seam for Supply Chain Intelligence.

A *signal* is an external intelligence input that nudges a base forecast and/or
contributes to a supply-risk score. Today there are NO built-in signals, so the
pipeline is a transparent pass-through (demand unchanged, risk = 0). The point is
the seam: future intelligence modules register a ``ForecastSignal`` and the
forecasting core, persistence, API, and reorder engine all keep working unchanged.

Planned signal categories (Phase 3 of the roadmap), each a future module that
calls ``register_signal(...)`` at import time:

    supplier      supplier reliability / financial-health adjustments
    freight       ocean/air freight cost & capacity pressure
    port          port congestion / dwell-time delays (lengthen effective lead time)
    commodity     raw-material price movements
    trade         tariffs, quotas, customs / trade-policy changes
    geopolitical  conflict, sanctions, strikes, weather/force-majeure risk

A signal returns a multiplicative ``demand_factor`` (1.0 = no change) and an
additive ``risk_delta`` (0..1 contribution). The pipeline composes factors,
sums risk (clamped to [0, 1]), and records every adjustment for explainability.
"""
from __future__ import annotations

import abc
import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from app.forecast.domain.models import ForecastResult

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")


class SignalCategory(str, Enum):
    SUPPLIER = "supplier"
    FREIGHT = "freight"
    PORT = "port"
    COMMODITY = "commodity"
    TRADE = "trade"
    GEOPOLITICAL = "geopolitical"


@dataclass(frozen=True)
class SignalContext:
    """Everything a signal may need to make a decision. Extensible: new fields can
    be added with defaults without breaking existing signals."""

    base: ForecastResult
    product_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    lead_time_days: Decimal = ZERO
    as_of: dt.date | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SignalAdjustment:
    """One signal's contribution. ``demand_factor`` multiplies daily demand;
    ``risk_delta`` adds to the 0..1 supply-risk score."""

    source: str
    category: str
    demand_factor: Decimal = ONE
    risk_delta: Decimal = ZERO
    reason: str = ""


@dataclass(frozen=True)
class AdjustedForecast:
    """Result of running the signal pipeline over a base forecast."""

    base: ForecastResult
    adjusted_daily_demand: Decimal
    risk_score: Decimal                       # 0..1
    adjustments: list[SignalAdjustment]

    @property
    def has_adjustments(self) -> bool:
        return bool(self.adjustments)


class ForecastSignal(abc.ABC):
    """A registered intelligence signal. Implementations must be side-effect free."""

    key: str
    category: str

    @abc.abstractmethod
    def evaluate(self, ctx: SignalContext) -> SignalAdjustment | None:
        """Return an adjustment, or None to abstain for this context."""


class SignalPipeline:
    """Composes registered signals over a base forecast. With no signals it is a
    pass-through, so forecasting works identically until intelligence is added."""

    def __init__(self, signals: list[ForecastSignal] | None = None) -> None:
        self.signals = signals or []

    def apply(self, ctx: SignalContext) -> AdjustedForecast:
        factor = ONE
        risk = ZERO
        applied: list[SignalAdjustment] = []
        for signal in self.signals:
            adj = signal.evaluate(ctx)
            if adj is None:
                continue
            factor *= adj.demand_factor
            risk += adj.risk_delta
            applied.append(adj)

        if risk < ZERO:
            risk = ZERO
        if risk > ONE:
            risk = ONE
        adjusted = (ctx.base.daily_demand * factor).quantize(_Q4, rounding=ROUND_HALF_UP)
        return AdjustedForecast(
            base=ctx.base,
            adjusted_daily_demand=adjusted,
            risk_score=risk.quantize(_Q4, rounding=ROUND_HALF_UP),
            adjustments=applied,
        )


# --------------------------------------------------------------------------- #
# Registry — future intelligence modules append here at import time.
# --------------------------------------------------------------------------- #
_SIGNAL_REGISTRY: list[ForecastSignal] = []


def register_signal(signal: ForecastSignal) -> None:
    _SIGNAL_REGISTRY.append(signal)


def registered_signals() -> list[ForecastSignal]:
    return list(_SIGNAL_REGISTRY)


def default_pipeline() -> SignalPipeline:
    """The pipeline of all currently-registered signals (empty today)."""
    return SignalPipeline(registered_signals())
