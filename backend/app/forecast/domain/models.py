"""Value objects for the demand-forecast engine (pure data, ``Decimal`` math).

The forecast engine produces a *demand signal* — an expected daily demand plus
its variability and a confidence score — from a window of historical daily
demand. That signal is what the reorder engine consumes (as average daily demand
and daily standard deviation); the forecast module deliberately does NOT compute
safety stock, reorder points, or order quantities. Those remain the single
responsibility of ``app.reorder.domain``.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")


class ForecastMethod(str, Enum):
    MOVING_AVERAGE = "moving_average"          # mean of the last N daily values
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"  # single exponential smoothing (SES)
    CROSTON = "croston"                        # Croston's method for intermittent demand
    SEASONAL = "seasonal"                      # classical seasonal decomposition (Holt-Winters family)


@dataclass(frozen=True)
class ForecastParams:
    """Tunables passed to a forecast provider. New providers may read new fields;
    existing providers ignore ones they don't use, so the params object can grow
    without breaking older methods."""

    window_days: int = 90       # length of history to consider
    horizon_days: int = 30      # how far ahead the forecast is anchored for accuracy tracking
    ma_window: int | None = None  # moving-average lookback (None = whole window)
    alpha: Decimal = Decimal("0.3")  # exponential-smoothing weight, (0, 1]
    croston_alpha: Decimal = Decimal("0.1")  # Croston smoothing weight, (0, 1] (small is usual)
    seasonal_period: int | None = None  # seasonal cycle length in days (None = auto-detect)


@dataclass(frozen=True)
class DemandPoint:
    """One day of observed demand. The series fed to the engine is dense
    (zero-filled); these points are the sparse, days-with-demand records that a
    repository returns before densification."""

    day: dt.date
    quantity: Decimal


@dataclass(frozen=True)
class ForecastResult:
    """Explainable output of a forecast for one (product, warehouse).

    ``daily_demand`` is the forward-looking expected demand per day. Multiply by
    a horizon to get expected demand over that horizon. ``std_dev_daily`` and
    ``daily_demand`` map directly onto the reorder engine's demand inputs.
    """

    method: str
    daily_demand: Decimal          # forecast: expected units/day going forward
    std_dev_daily: Decimal         # population std dev of the historical daily series
    confidence: Decimal            # deterministic score in [0, 1]
    window_days: int               # length of the daily series considered
    observations: int              # number of daily buckets in the series
    days_with_demand: int          # buckets with quantity > 0
    total_demand: Decimal          # sum of the series over the window

    @property
    def avg_monthly(self) -> Decimal:
        return self.daily_demand * Decimal(30)

    def expected_over(self, horizon_days: int | Decimal) -> Decimal:
        return self.daily_demand * Decimal(horizon_days)
