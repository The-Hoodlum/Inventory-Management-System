"""Deterministic demand-forecasting methods (pure functions, ``Decimal`` math).

Two methods are supported, both operating on a *dense, zero-filled* daily demand
series ordered oldest -> newest:

  moving_average            Forecast = mean of the last ``window`` daily values.
                            With a zero-filled series this is the true average
                            daily demand over the window.

  single_exponential_smoothing
                            level_t = alpha * y_t + (1 - alpha) * level_{t-1}
                            Forecast = the final smoothed level. Recent demand is
                            weighted more heavily as ``alpha`` -> 1.

``build_series`` turns sparse (day, qty) points into the dense series the methods
require, so callers never have to materialise zero-sales days themselves.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from app.forecast.domain.exceptions import InvalidForecastInput
from app.forecast.domain.models import DemandPoint, ForecastMethod, ForecastResult
from app.forecast.domain.confidence import forecast_confidence
from app.forecast.domain.patterns import detect_seasonality, linear_trend

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Series construction
# --------------------------------------------------------------------------- #
def build_series(
    points: Iterable[DemandPoint], *, end_day: dt.date, window_days: int
) -> list[Decimal]:
    """Build a dense daily series of length ``window_days`` ending on ``end_day``
    (inclusive), oldest -> newest. Days without a point contribute 0; points
    outside the window are ignored. Duplicate days are summed."""
    if window_days < 1:
        raise InvalidForecastInput("window_days must be >= 1")
    start_day = end_day - dt.timedelta(days=window_days - 1)
    buckets: dict[dt.date, Decimal] = {}
    for p in points:
        if start_day <= p.day <= end_day:
            buckets[p.day] = buckets.get(p.day, ZERO) + Decimal(p.quantity)
    return [
        buckets.get(start_day + dt.timedelta(days=i), ZERO) for i in range(window_days)
    ]


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def mean(series: list[Decimal]) -> Decimal:
    if not series:
        return ZERO
    return sum(series, ZERO) / Decimal(len(series))


def population_std(series: list[Decimal]) -> Decimal:
    """Population standard deviation of the daily series (matches the reorder
    engine's variance convention over a zero-filled window)."""
    n = len(series)
    if n == 0:
        return ZERO
    m = mean(series)
    var = sum(((x - m) * (x - m) for x in series), ZERO) / Decimal(n)
    if var < 0:  # guard tiny negative from rounding
        var = ZERO
    return var.sqrt()


# --------------------------------------------------------------------------- #
# Point-forecast methods
# --------------------------------------------------------------------------- #
def moving_average(series: list[Decimal], window: int | None = None) -> Decimal:
    """Mean of the last ``window`` values (all values when ``window`` is None)."""
    if not series:
        return ZERO
    if window is not None:
        if window < 1:
            raise InvalidForecastInput("window must be >= 1")
        series = series[-window:]
    return mean(series)


def single_exponential_smoothing(series: list[Decimal], alpha: Decimal) -> Decimal:
    """One-step-ahead SES forecast = the final smoothed level. ``alpha`` in (0, 1]."""
    a = Decimal(alpha)
    if not (ZERO < a <= Decimal("1")):
        raise InvalidForecastInput("alpha must be in the range (0, 1]")
    if not series:
        return ZERO
    level = series[0]
    one_minus = Decimal("1") - a
    for y in series[1:]:
        level = a * y + one_minus * level
    return level


def croston(series: list[Decimal], alpha: Decimal = Decimal("0.1")) -> Decimal:
    """Croston's method for intermittent demand.

    Smooths the non-zero demand *sizes* and the *intervals* between them separately,
    then forecasts the per-period demand rate as ``size / interval``. ``alpha`` in
    (0, 1]; small values (~0.1) are usual. The result is expected demand *per period*
    (per day for a daily series) — exactly the average-daily-demand signal the
    reorder engine consumes.

    Unlike a moving average, it is not dragged toward zero by the long runs of zeros
    that define intermittent demand: it reasons about "how much, how often". The size
    and interval estimates are seeded from the mean observed demand size and mean
    inter-demand interval (rather than the first occurrence), so the forecast is
    insensitive to where the window happens to start in the demand cycle and lands on
    the correct rate immediately for stationary demand, then adapts as the rate
    drifts. The Syntetos-Boylan bias correction is a future refinement.
    """
    a = Decimal(alpha)
    if not (ZERO < a <= ONE):
        raise InvalidForecastInput("alpha must be in the range (0, 1]")
    events = [(i, v) for i, v in enumerate(series) if v > 0]
    m = len(events)
    if m == 0:
        return ZERO
    indices = [i for i, _ in events]
    size = sum((v for _, v in events), ZERO) / Decimal(m)       # ẑ: mean demand size
    if m >= 2:
        interval = Decimal(indices[-1] - indices[0]) / Decimal(m - 1)  # p̂: mean gap
    else:
        interval = Decimal(indices[0] + 1)  # single occurrence: periods up to it
    one_minus = ONE - a
    prev_idx = indices[0]
    for idx, val in events[1:]:
        gap = Decimal(idx - prev_idx)
        size = a * val + one_minus * size
        interval = a * gap + one_minus * interval
        prev_idx = idx
    if interval <= 0:
        return ZERO
    return size / interval


def seasonal_indices(series: list[Decimal], period: int) -> list[Decimal]:
    """Multiplicative seasonal indices of length ``period`` (one per phase of the
    cycle), normalised to average 1.0. Index *r* is the mean demand of the phase-*r*
    positions divided by the overall mean, so >1 marks an above-average phase.
    All-ones (no seasonal signal) when the series has no demand."""
    if period < 1:
        raise InvalidForecastInput("period must be >= 1")
    grand = mean(series)
    if grand <= 0:
        return [ONE] * period
    sums = [ZERO] * period
    counts = [0] * period
    for i, y in enumerate(series):
        r = i % period
        sums[r] += y
        counts[r] += 1
    raw = [
        (sums[r] / Decimal(counts[r]) / grand) if counts[r] else ONE
        for r in range(period)
    ]
    avg = sum(raw, ZERO) / Decimal(period)  # renormalise to mean 1 (uneven phase counts)
    if avg <= 0:
        return [ONE] * period
    return [idx / avg for idx in raw]


def _deseasonalize(series: list[Decimal], indices: list[Decimal], period: int) -> list[Decimal]:
    out: list[Decimal] = []
    for i, y in enumerate(series):
        idx = indices[i % period]
        out.append(y / idx if idx > 0 else y)
    return out


def seasonal_point(
    series: list[Decimal],
    *,
    period: int | None = None,
    horizon_days: int = 30,
    candidate_periods: tuple[int, ...] | None = None,
) -> Decimal:
    """Seasonal point forecast collapsed to expected average daily demand over the
    next ``horizon_days``.

    Classical multiplicative decomposition — the deterministic, fully inspectable
    cousin of Holt-Winters: estimate seasonal indices, deseasonalise, fit a level
    and linear trend on the deseasonalised series, then project that line across the
    forecast horizon, re-apply the seasonal indices for each forward day, and average
    to a single daily figure. Deseasonalising *before* the trend fit keeps the
    level/trend honest — not biased by where the window happens to end in the cycle.

    Falls back to a plain moving average when there is too little data to establish a
    season (fewer than two full cycles) or no period is detected.
    """
    n = len(series)
    if period is None:
        period, _ = detect_seasonality(series, candidate_periods=candidate_periods)
    if not period or period < 2 or n < 2 * period:
        return moving_average(series)  # not enough signal for a seasonal model
    indices = seasonal_indices(series, period)
    des = _deseasonalize(series, indices, period)
    intercept, slope = linear_trend(des)
    horizon = horizon_days if horizon_days and horizon_days > 0 else 1
    total = ZERO
    for k in range(horizon):
        pos = n + k  # forward day position continuing the fitted line (series is 0..n-1)
        level = intercept + slope * Decimal(pos)
        if level < 0:
            level = ZERO
        total += level * indices[pos % period]
    return total / Decimal(horizon)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def forecast(
    series: list[Decimal],
    *,
    method: ForecastMethod = ForecastMethod.MOVING_AVERAGE,
    ma_window: int | None = None,
    alpha: Decimal = Decimal("0.3"),
    croston_alpha: Decimal = Decimal("0.1"),
    seasonal_period: int | None = None,
    horizon_days: int = 30,
) -> ForecastResult:
    """Run the chosen method over a dense daily series and package the result
    (point forecast + variability + confidence + descriptive stats)."""
    if method is ForecastMethod.MOVING_AVERAGE:
        point = moving_average(series, ma_window)
    elif method is ForecastMethod.EXPONENTIAL_SMOOTHING:
        point = single_exponential_smoothing(series, alpha)
    elif method is ForecastMethod.CROSTON:
        point = croston(series, croston_alpha)
    elif method is ForecastMethod.SEASONAL:
        point = seasonal_point(series, period=seasonal_period, horizon_days=horizon_days)
    else:  # pragma: no cover - exhaustive enum
        raise InvalidForecastInput(f"Unknown forecast method: {method}")

    return package_result(series, point, method)


def package_result(
    series: list[Decimal], point: Decimal, method: ForecastMethod
) -> ForecastResult:
    """Wrap a point forecast with variability, confidence, and descriptive stats.

    Shared by the orchestrator and every provider so a new forecasting method only
    has to produce a point estimate — the packaging stays identical and tested.
    """
    n = len(series)
    return ForecastResult(
        method=method.value,
        daily_demand=_q(point if point > 0 else ZERO),
        std_dev_daily=_q(population_std(series)),
        confidence=forecast_confidence(series),
        window_days=n,
        observations=n,
        days_with_demand=sum(1 for x in series if x > 0),
        total_demand=_q(sum(series, ZERO)),
    )
