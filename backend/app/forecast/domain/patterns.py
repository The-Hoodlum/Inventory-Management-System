"""Demand-pattern detection — the measured companion to the declared demand type.

Where ``ProductProfile.demand_type`` records what a planner *says* a SKU's demand
looks like, this module *measures* it from the actual daily series, deterministically
and without ML, so every classification is auditable:

  intermittency   ADI (average demand interval) and CV² of the non-zero demand
                  sizes, combined into the Syntetos-Boylan-Croston quadrant
                  (smooth / erratic / intermittent / lumpy).
  trend           an ordinary least-squares slope over the series (units/day), with
                  a normalised 0..1 strength and an up / down / flat direction.
  seasonality     the lag (period) of the strongest autocorrelation peak and its
                  0..1 strength; daily series typically peak at lag 7 (weekly).

``analyze`` rolls these into a ``DemandPattern`` whose ``suggested_demand_type``
speaks the same vocabulary as ``app.schemas.product.DemandType`` and whose
``suggested_method`` is a forecast-provider key — so detection can both recommend a
product's demand_type and pick a forecasting method when the caller doesn't.

Pure and dependency-free (its own mean/std) so it cannot create an import cycle with
``methods`` (which imports the trend fit and seasonality scan from here) and stays
trivially unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")

# Syntetos-Boylan-Croston cut-offs separating the four demand categories.
ADI_CUTOFF = Decimal("1.32")
CV2_CUTOFF = Decimal("0.49")

# Autocorrelation at/above which a lag is accepted as a genuine season.
SEASONAL_STRENGTH_CUTOFF = Decimal("0.3")
# A slope stays "flat" until the fitted change over the window reaches this
# fraction of mean demand — keeps noise from being read as a trend.
TREND_STRENGTH_CUTOFF = Decimal("0.15")

# Calendar cycles probed by default: weekly, fortnightly, monthly, quarterly,
# yearly. Scanning named cycles (rather than every lag) is cheaper and far more
# interpretable — a peak at 7 reads as "weekly", not an arbitrary lag.
DEFAULT_SEASONAL_PERIODS = (7, 14, 30, 90, 365)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def _mean(series: list[Decimal]) -> Decimal:
    if not series:
        return ZERO
    return sum(series, ZERO) / Decimal(len(series))


def _std(series: list[Decimal], m: Decimal) -> Decimal:
    n = len(series)
    if n == 0:
        return ZERO
    var = sum(((x - m) * (x - m) for x in series), ZERO) / Decimal(n)
    if var < 0:  # guard tiny negative from rounding
        var = ZERO
    return var.sqrt()


# --------------------------------------------------------------------------- #
# Intermittency
# --------------------------------------------------------------------------- #
def average_demand_interval(series: list[Decimal]) -> Decimal | None:
    """ADI = periods / number of demand occurrences. ``None`` when there is no
    demand. ADI = 1 means demand every period; larger means sparser demand."""
    events = sum(1 for x in series if x > 0)
    if events == 0:
        return None
    return _q(Decimal(len(series)) / Decimal(events))


def demand_size_cv_squared(series: list[Decimal]) -> Decimal | None:
    """Squared coefficient of variation of the *non-zero* demand sizes. ``None``
    with fewer than two occurrences (size variability is undefined)."""
    sizes = [x for x in series if x > 0]
    if len(sizes) < 2:
        return None
    m = _mean(sizes)
    if m <= 0:
        return None
    cv = _std(sizes, m) / m
    return _q(cv * cv)


def classify_demand(series: list[Decimal]) -> str:
    """Syntetos-Boylan-Croston category from ADI and the CV² of demand sizes::

        ADI  < 1.32, CV² < 0.49  -> smooth        (regular timing, steady size)
        ADI  < 1.32, CV² >= 0.49 -> erratic       (regular timing, variable size)
        ADI >= 1.32, CV² < 0.49  -> intermittent  (sparse timing, steady size)
        ADI >= 1.32, CV² >= 0.49 -> lumpy         (sparse timing, variable size)

    These four labels are exactly the non-seasonal members of ``DemandType``. With
    no demand the series can't be characterised, so it defaults to ``smooth``.
    """
    adi = average_demand_interval(series)
    if adi is None:
        return "smooth"
    cv2 = demand_size_cv_squared(series)
    if cv2 is None:
        cv2 = ZERO  # a single occurrence: treat the size as non-variable
    sparse = adi >= ADI_CUTOFF
    variable = cv2 >= CV2_CUTOFF
    if sparse and variable:
        return "lumpy"
    if sparse:
        return "intermittent"
    if variable:
        return "erratic"
    return "smooth"


# --------------------------------------------------------------------------- #
# Trend
# --------------------------------------------------------------------------- #
def linear_trend(series: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Ordinary least-squares fit over x = 0..n-1. Returns ``(intercept, slope)``
    where the fitted value at position x is ``intercept + slope * x``. Flat
    (slope 0) with fewer than two points or zero x-variance."""
    n = len(series)
    if n < 2:
        return (series[0] if n else ZERO, ZERO)
    x_mean = Decimal(n - 1) / Decimal(2)
    y_mean = _mean(series)
    sxx = ZERO
    sxy = ZERO
    for i, y in enumerate(series):
        dx = Decimal(i) - x_mean
        sxx += dx * dx
        sxy += dx * (y - y_mean)
    if sxx == 0:
        return (y_mean, ZERO)
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    return (intercept, slope)


def detect_trend(series: list[Decimal]) -> tuple[str, Decimal, Decimal]:
    """Return ``(direction, slope, strength)``. ``direction`` is up / down / flat;
    ``slope`` is units/day; ``strength`` in [0, 1] is the fitted change across the
    window relative to mean demand (capped at 1). Reads as flat until the strength
    clears ``TREND_STRENGTH_CUTOFF``."""
    n = len(series)
    _, slope = linear_trend(series)
    m = _mean(series)
    if n < 2 or m <= 0 or slope == 0:
        return ("flat", _q(slope), ZERO)
    total_change = slope * Decimal(n - 1)  # fitted rise/fall across the window
    strength = abs(total_change) / m
    if strength > ONE:
        strength = ONE
    if strength < TREND_STRENGTH_CUTOFF:
        return ("flat", _q(slope), _q(strength))
    return ("up" if slope > 0 else "down", _q(slope), _q(strength))


# --------------------------------------------------------------------------- #
# Seasonality
# --------------------------------------------------------------------------- #
def autocorrelation(series: list[Decimal], lag: int) -> Decimal:
    """Sample autocorrelation at ``lag`` (the series correlated with itself shifted
    by ``lag``). 0 when the lag is out of range or the series has no variance."""
    n = len(series)
    if lag < 1 or lag >= n:
        return ZERO
    m = _mean(series)
    denom = sum(((x - m) * (x - m) for x in series), ZERO)
    if denom <= 0:
        return ZERO
    num = ZERO
    for t in range(lag, n):
        num += (series[t] - m) * (series[t - lag] - m)
    return num / denom


def detect_seasonality(
    series: list[Decimal], *, candidate_periods: tuple[int, ...] | None = None
) -> tuple[int | None, Decimal]:
    """Return ``(period, strength)``: the candidate lag with the strongest positive
    autocorrelation, or ``(None, strength)`` if none clears the strength cut-off. A
    period is only considered when the window holds at least two full cycles.

    The series is *detrended* first: a trend inflates autocorrelation at every lag
    and would otherwise masquerade as seasonality. Seasonality is genuine periodicity
    in the residuals around the trend line, not the smoothness a trend creates.
    """
    n = len(series)
    periods = DEFAULT_SEASONAL_PERIODS if candidate_periods is None else candidate_periods
    intercept, slope = linear_trend(series)
    residuals = [series[i] - (intercept + slope * Decimal(i)) for i in range(n)]
    best_period: int | None = None
    best_strength = ZERO
    for m in periods:
        if m < 2 or m > n // 2:  # need two full cycles to trust a season
            continue
        r = autocorrelation(residuals, m)
        if r > best_strength:
            best_strength = r
            best_period = m
    if best_period is None or best_strength < SEASONAL_STRENGTH_CUTOFF:
        return (None, _q(best_strength if best_strength > 0 else ZERO))
    return (best_period, _q(best_strength))


# --------------------------------------------------------------------------- #
# Composite pattern
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DemandPattern:
    """An explainable, measured description of a demand series."""

    n: int                              # length of the daily series considered
    days_with_demand: int               # buckets with quantity > 0
    adi: Decimal | None                 # average demand interval (None = no demand)
    cv_squared: Decimal | None          # CV² of non-zero sizes (None = < 2 events)
    classification: str                 # smooth | erratic | intermittent | lumpy
    trend_direction: str                # up | down | flat
    trend_slope: Decimal                # units/day
    trend_strength: Decimal             # 0..1
    seasonal: bool                      # a season cleared the strength cut-off
    seasonal_period: int | None         # detected cycle length (days)
    seasonal_strength: Decimal          # 0..1 autocorrelation at the period
    suggested_demand_type: str | None   # DemandType vocabulary; None when no demand
    suggested_method: str               # forecast-provider key
    drivers: list[str] = field(default_factory=list)

    @property
    def has_demand(self) -> bool:
        return self.days_with_demand > 0


def suggested_method_for(pattern: DemandPattern) -> str:
    """Forecast-provider key best suited to a detected pattern.

    Seasonality wins (it benefits most from the seasonal method); otherwise the SBC
    class maps to its method, and a trending-but-otherwise-smooth series prefers
    exponential smoothing (recency-weighted) over a flat moving average.
    """
    if pattern.seasonal:
        return "seasonal"
    if pattern.classification in ("intermittent", "lumpy"):
        return "croston"
    if pattern.classification == "erratic":
        return "exponential_smoothing"
    if pattern.trend_direction != "flat":
        return "exponential_smoothing"
    return "moving_average"


def analyze(
    series: list[Decimal], *, candidate_periods: tuple[int, ...] | None = None
) -> DemandPattern:
    """Measure intermittency, trend, and seasonality and roll them into a
    ``DemandPattern`` with a suggested demand_type and forecast method."""
    n = len(series)
    days = sum(1 for x in series if x > 0)
    adi = average_demand_interval(series)
    cv2 = demand_size_cv_squared(series)
    classification = classify_demand(series)
    direction, slope, t_strength = detect_trend(series)
    period, s_strength = detect_seasonality(series, candidate_periods=candidate_periods)
    seasonal = period is not None

    drivers: list[str] = []
    if days == 0:
        drivers.append("no demand in window")
    else:
        if adi is not None:
            drivers.append(f"ADI={adi} ({'sparse' if adi >= ADI_CUTOFF else 'regular'})")
        if cv2 is not None:
            drivers.append(f"CV²={cv2} ({'variable' if cv2 >= CV2_CUTOFF else 'steady'} size)")
        drivers.append(f"class={classification}")
    if seasonal:
        drivers.append(f"seasonal period={period}d (r={s_strength})")
    if direction != "flat":
        drivers.append(f"trend {direction} (strength={t_strength})")

    # The suggested demand_type aligns to the DemandType vocabulary; a detected
    # season is the dominant descriptor and overrides the SBC class.
    if days == 0:
        suggested_type: str | None = None
    elif seasonal:
        suggested_type = "seasonal"
    else:
        suggested_type = classification

    pattern = DemandPattern(
        n=n,
        days_with_demand=days,
        adi=adi,
        cv_squared=cv2,
        classification=classification,
        trend_direction=direction,
        trend_slope=slope,
        trend_strength=t_strength,
        seasonal=seasonal,
        seasonal_period=period,
        seasonal_strength=s_strength,
        suggested_demand_type=suggested_type,
        suggested_method="moving_average",
        drivers=drivers,
    )
    method = "moving_average" if days == 0 else suggested_method_for(pattern)
    return replace(pattern, suggested_method=method)
