"""Unit tests for pure demand-pattern detection (ADI/CV², trend, seasonality)."""
from __future__ import annotations

from decimal import Decimal

from app.forecast.domain.patterns import (
    analyze,
    autocorrelation,
    average_demand_interval,
    classify_demand,
    demand_size_cv_squared,
    detect_seasonality,
    detect_trend,
    linear_trend,
    suggested_method_for,
)

D = Decimal


# --------------------------------- ADI ------------------------------------ #
def test_adi_every_period_is_one():
    assert average_demand_interval([D("4")] * 10) == D("1.0000")


def test_adi_counts_periods_per_demand_occurrence():
    series = [D("10"), D("0"), D("0"), D("0"), D("10"), D("0"), D("0"), D("0"), D("10"), D("0")]
    assert average_demand_interval(series) == D("3.3333")  # 10 periods / 3 events


def test_adi_none_when_no_demand():
    assert average_demand_interval([D("0")] * 8) is None


# ------------------------------- CV² -------------------------------------- #
def test_cv_squared_zero_for_constant_sizes():
    # demand sizes all equal -> no size variability
    assert demand_size_cv_squared([D("5"), D("0"), D("5"), D("0"), D("5")]) == D("0.0000")


def test_cv_squared_none_with_fewer_than_two_occurrences():
    assert demand_size_cv_squared([D("0"), D("0"), D("9")]) is None


def test_cv_squared_known_value():
    # nonzero sizes 2,4,4,4,5,5,7,9 -> mean 5, std 2 -> CV 0.4 -> CV² 0.16
    series = [D(x) for x in (2, 4, 4, 4, 5, 5, 7, 9)]
    assert demand_size_cv_squared(series) == D("0.1600")


# --------------------------- SBC classification --------------------------- #
def test_classify_smooth():
    assert classify_demand([D("5")] * 20) == "smooth"


def test_classify_erratic_regular_timing_variable_size():
    # every period has demand (ADI 1) but sizes swing 1/9 -> CV² 0.64
    assert classify_demand([D("1"), D("9")] * 10) == "erratic"


def test_classify_intermittent_sparse_steady_size():
    # demand every 5th day, constant size -> ADI 5, CV² 0
    assert classify_demand(([D("10")] + [D("0")] * 4) * 4) == "intermittent"


def test_classify_lumpy_sparse_and_variable():
    series = (
        [D("10")] + [D("0")] * 4
        + [D("2")] + [D("0")] * 4
        + [D("8")] + [D("0")] * 4
        + [D("1")] + [D("0")] * 4
    )
    assert classify_demand(series) == "lumpy"


def test_classify_no_demand_defaults_to_smooth():
    assert classify_demand([D("0")] * 10) == "smooth"


# ------------------------------- trend ------------------------------------ #
def test_linear_trend_hand_computed():
    # points (0,10),(1,20): slope 10, value at x=0 is 10
    intercept, slope = linear_trend([D("10"), D("20")])
    assert (intercept, slope) == (D("10"), D("10"))


def test_detect_trend_up():
    direction, slope, strength = detect_trend([D(i) for i in range(10)])
    assert direction == "up"
    assert slope == D("1.0000")
    assert strength == D("1.0000")  # change (9) far exceeds the mean (4.5) -> capped


def test_detect_trend_down():
    direction, _, _ = detect_trend([D(i) for i in range(10, 0, -1)])
    assert direction == "down"


def test_detect_trend_flat_for_constant():
    direction, slope, strength = detect_trend([D("5")] * 10)
    assert direction == "flat"
    assert slope == D("0.0000")
    assert strength == D("0")


# ---------------------------- seasonality --------------------------------- #
def _weekly(weeks: int = 8) -> list[Decimal]:
    # strong day-0-of-week spike: 10 on day 0 of each week, 1 otherwise
    return [D("10") if i % 7 == 0 else D("1") for i in range(weeks * 7)]


def test_autocorrelation_zero_for_constant_series():
    assert autocorrelation([D("5")] * 20, 7) == D("0")


def test_detect_seasonality_finds_weekly_period():
    period, strength = detect_seasonality(_weekly(), candidate_periods=(7,))
    assert period == 7
    assert strength > D("0.3")


def test_detect_seasonality_none_for_constant():
    period, _ = detect_seasonality([D("5")] * 60)
    assert period is None


def test_detect_seasonality_ignores_pure_trend():
    # a rising ramp has high autocorrelation at every lag, but detrending removes it
    period, _ = detect_seasonality([D(i) for i in range(60)])
    assert period is None


# ------------------------------- analyze ---------------------------------- #
def test_analyze_intermittent_recommends_croston():
    p = analyze(([D("10")] + [D("0")] * 4) * 6)
    assert p.classification == "intermittent"
    assert p.suggested_demand_type == "intermittent"
    assert p.suggested_method == "croston"
    assert p.has_demand


def test_analyze_seasonal_overrides_class_and_recommends_seasonal():
    p = analyze(_weekly(), candidate_periods=(7,))
    assert p.seasonal is True and p.seasonal_period == 7
    assert p.suggested_demand_type == "seasonal"  # season dominates the SBC label
    assert p.suggested_method == "seasonal"


def test_analyze_no_demand_is_safe():
    p = analyze([D("0")] * 30)
    assert p.days_with_demand == 0
    assert p.suggested_demand_type is None
    assert p.suggested_method == "moving_average"
    assert "no demand in window" in p.drivers


def test_suggested_method_for_smooth_trending_prefers_smoothing():
    # smooth, no season, but trending -> exponential smoothing over flat MA
    p = analyze([D(i) for i in range(30)])
    assert p.classification == "smooth"
    assert p.trend_direction == "up"
    assert suggested_method_for(p) == "exponential_smoothing"
