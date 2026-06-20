"""Unit tests for the pure forecast methods and series construction."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.forecast.domain.exceptions import InvalidForecastInput
from app.forecast.domain.methods import (
    build_series,
    croston,
    mean,
    moving_average,
    population_std,
    seasonal_indices,
    seasonal_point,
    single_exponential_smoothing,
    forecast,
)
from app.forecast.domain.models import DemandPoint, ForecastMethod

D = Decimal


# ------------------------------ build_series ------------------------------ #
def test_build_series_zero_fills_and_orders_oldest_to_newest():
    end = dt.date(2026, 1, 10)
    points = [
        DemandPoint(dt.date(2026, 1, 10), D("5")),
        DemandPoint(dt.date(2026, 1, 8), D("3")),
    ]
    series = build_series(points, end_day=end, window_days=5)
    # window = Jan 6..10 ; demand on the 8th (3) and 10th (5)
    assert series == [D("0"), D("0"), D("3"), D("0"), D("5")]
    assert len(series) == 5


def test_build_series_ignores_points_outside_window_and_sums_duplicates():
    end = dt.date(2026, 1, 10)
    points = [
        DemandPoint(dt.date(2026, 1, 1), D("99")),   # before window -> ignored
        DemandPoint(dt.date(2026, 1, 10), D("2")),
        DemandPoint(dt.date(2026, 1, 10), D("4")),   # duplicate day -> summed
    ]
    series = build_series(points, end_day=end, window_days=3)
    assert series == [D("0"), D("0"), D("6")]


def test_build_series_rejects_bad_window():
    with pytest.raises(InvalidForecastInput):
        build_series([], end_day=dt.date(2026, 1, 1), window_days=0)


# ------------------------------ statistics -------------------------------- #
def test_mean_and_std_of_constant_series():
    s = [D("4")] * 10
    assert mean(s) == D("4")
    assert population_std(s) == D("0")


def test_population_std_known_value():
    # series [2,4,4,4,5,5,7,9] -> mean 5, population variance 4, std 2
    s = [D(x) for x in (2, 4, 4, 4, 5, 5, 7, 9)]
    assert mean(s) == D("5")
    assert population_std(s) == D("2")


def test_mean_empty_is_zero():
    assert mean([]) == D("0")


# --------------------------- moving average ------------------------------- #
def test_moving_average_full_window():
    assert moving_average([D("10"), D("20"), D("30")]) == D("20")


def test_moving_average_last_n():
    assert moving_average([D("10"), D("20"), D("30"), D("40")], window=2) == D("35")


def test_moving_average_empty_is_zero():
    assert moving_average([]) == D("0")


def test_moving_average_rejects_bad_window():
    with pytest.raises(InvalidForecastInput):
        moving_average([D("1")], window=0)


# ----------------------- exponential smoothing ---------------------------- #
def test_ses_constant_series_returns_constant():
    assert single_exponential_smoothing([D("7")] * 6, D("0.4")) == D("7")


def test_ses_alpha_one_returns_last_value():
    assert single_exponential_smoothing([D("3"), D("8"), D("5")], D("1")) == D("5")


def test_ses_hand_computed():
    # level0 = 10 ; level1 = 0.5*20 + 0.5*10 = 15
    assert single_exponential_smoothing([D("10"), D("20")], D("0.5")) == D("15")


def test_ses_empty_is_zero():
    assert single_exponential_smoothing([], D("0.3")) == D("0")


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1.5")])
def test_ses_rejects_alpha_out_of_range(bad):
    with pytest.raises(InvalidForecastInput):
        single_exponential_smoothing([D("1"), D("2")], bad)


# ----------------------------- orchestrator ------------------------------- #
def test_forecast_moving_average_packages_signal_and_stats():
    s = [D("10")] * 30
    r = forecast(s, method=ForecastMethod.MOVING_AVERAGE)
    assert r.method == "moving_average"
    assert r.daily_demand == D("10.0000")
    assert r.std_dev_daily == D("0.0000")
    assert r.observations == 30
    assert r.days_with_demand == 30
    assert r.total_demand == D("300.0000")
    assert r.avg_monthly == D("300.0000")
    assert r.expected_over(7) == D("70.0000")


def test_forecast_exponential_smoothing_weights_recent_demand():
    # rising demand: SES should land above the simple long-run mean
    s = [D("2")] * 20 + [D("12")] * 10
    r = forecast(s, method=ForecastMethod.EXPONENTIAL_SMOOTHING, alpha=D("0.5"))
    assert r.method == "exponential_smoothing"
    assert r.daily_demand > moving_average(s)


def test_forecast_clamps_negative_point_to_zero():
    # demand series is never negative, but the clamp is a safety net
    r = forecast([D("0")] * 10, method=ForecastMethod.MOVING_AVERAGE)
    assert r.daily_demand == D("0.0000")
    assert r.days_with_demand == 0


# -------------------------------- croston --------------------------------- #
def test_croston_empty_and_zero_series_are_zero():
    assert croston([]) == D("0")
    assert croston([D("0")] * 10) == D("0")


def test_croston_constant_series_returns_constant_rate():
    # demand every period at size 4 -> size 4 every 1 period -> rate 4
    assert croston([D("4")] * 10) == D("4")


def test_croston_single_event_is_size_over_interval():
    # one demand of 10 on the 5th period -> 10 / 5 = 2 per period
    assert croston([D("0"), D("0"), D("0"), D("0"), D("10")]) == D("2")


def test_croston_hand_computed_two_events():
    # events at index 0 and 4, both size 10, alpha 0.5. Seeded from the means:
    #   size = 10 (mean size) ; interval = 4 (mean gap). The one update (gap 4,
    #   size 10) leaves both unchanged -> rate = 10 / 4 = 2.5
    assert croston([D("10"), D("0"), D("0"), D("0"), D("10")], D("0.5")) == D("2.5")


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1.5")])
def test_croston_rejects_alpha_out_of_range(bad):
    with pytest.raises(InvalidForecastInput):
        croston([D("1"), D("0"), D("2")], bad)


def test_croston_not_dragged_down_by_zeros_versus_moving_average():
    # sparse but steady demand: Croston reports the demand *rate*, MA the daily mean
    series = ([D("10")] + [D("0")] * 4) * 6   # 6 demands of 10, every 5th day
    assert croston(series) == D("2")           # 10 per 5 periods
    assert moving_average(series) == D("2")    # 60 / 30 — agree for stationary demand


# -------------------------------- seasonal -------------------------------- #
def _weekly(weeks: int = 8) -> list[Decimal]:
    return [D("10") if i % 7 == 0 else D("1") for i in range(weeks * 7)]


def test_seasonal_indices_normalise_to_mean_one_and_flag_the_peak():
    indices = seasonal_indices(_weekly(weeks=4), period=7)
    assert len(indices) == 7
    assert abs(sum(indices, D("0")) - D("7")) < D("0.0001")  # mean of indices == 1
    assert indices[0] > indices[1]                            # day-0 is the peak


def test_seasonal_point_falls_back_to_moving_average_without_two_cycles():
    short = [D("3")] * 10
    assert seasonal_point(short, period=7) == moving_average(short)


def test_seasonal_point_is_a_sensible_level_for_balanced_season():
    series = _weekly()                       # mean ~2.29, no trend
    point = seasonal_point(series, period=7, horizon_days=30)
    assert D("1.5") < point < D("3.5")


def test_seasonal_point_projects_an_upward_trend_above_history():
    # weekly spike plus a clear upward trend -> forward level beats the historical mean
    series = [D(i) / D("10") + (D("5") if i % 7 == 0 else D("0")) for i in range(56)]
    point = seasonal_point(series, period=7, horizon_days=30)
    assert point > mean(series)


# ----------------------- orchestrator: new methods ------------------------ #
def test_forecast_orchestrator_runs_croston():
    r = forecast([D("0"), D("0"), D("0"), D("0"), D("10")], method=ForecastMethod.CROSTON)
    assert r.method == "croston"
    assert r.daily_demand == D("2.0000")


def test_forecast_orchestrator_runs_seasonal():
    r = forecast(_weekly(), method=ForecastMethod.SEASONAL, seasonal_period=7)
    assert r.method == "seasonal"
    assert r.daily_demand > D("0")
