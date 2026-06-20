"""Unit tests for the deterministic forecast-confidence score."""
from __future__ import annotations

from decimal import Decimal

from app.forecast.domain.confidence import forecast_confidence

D = Decimal


def test_empty_series_has_zero_confidence():
    assert forecast_confidence([]) == D("0")


def test_no_demand_signal_has_zero_confidence():
    assert forecast_confidence([D("0")] * 60) == D("0")


def test_steady_demand_with_full_history_is_maximal():
    # CV = 0 (stability 1), n == target (sufficiency 1) -> confidence 1
    assert forecast_confidence([D("5")] * 60, target_observations=60) == D("1.0000")


def test_short_history_reduces_confidence_via_sufficiency():
    # steady demand but only half the target history -> ~0.5
    assert forecast_confidence([D("5")] * 30, target_observations=60) == D("0.5000")


def test_volatile_demand_scores_below_steady_demand():
    steady = [D("5")] * 60
    volatile = [D("10") if i % 2 == 0 else D("0") for i in range(60)]
    c_steady = forecast_confidence(steady, target_observations=60)
    c_volatile = forecast_confidence(volatile, target_observations=60)
    assert c_volatile < c_steady
    # CV = 1 here -> stability 0.5, sufficiency 1 -> 0.5
    assert c_volatile == D("0.5000")


def test_confidence_is_bounded_unit_interval():
    c = forecast_confidence([D("3"), D("9"), D("1"), D("7"), D("4")], target_observations=60)
    assert D("0") <= c <= D("1")
