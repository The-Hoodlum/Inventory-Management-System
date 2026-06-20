"""Unit tests for the pluggable forecast provider registry."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.forecast.domain import providers
from app.forecast.domain.exceptions import InvalidForecastInput
from app.forecast.domain.methods import forecast as orchestrate
from app.forecast.domain.models import ForecastMethod, ForecastParams

D = Decimal


def test_builtin_providers_are_registered():
    keys = {p.key for p in providers.available_providers()}
    assert {"moving_average", "exponential_smoothing"} <= keys
    assert providers.default_provider_key() == "moving_average"


def test_get_unknown_provider_raises():
    with pytest.raises(InvalidForecastInput):
        providers.get_provider("does_not_exist")


def test_moving_average_provider_matches_orchestrator():
    series = [D("4")] * 30
    params = ForecastParams(window_days=30)
    result = providers.get_provider("moving_average").generate(series, params)
    expected = orchestrate(series, method=ForecastMethod.MOVING_AVERAGE)
    assert result.daily_demand == expected.daily_demand == D("4.0000")
    assert result.method == "moving_average"


def test_exponential_smoothing_provider_uses_alpha():
    series = [D("2")] * 20 + [D("12")] * 10
    params = ForecastParams(alpha=D("0.5"))
    result = providers.get_provider("exponential_smoothing").generate(series, params)
    expected = orchestrate(series, method=ForecastMethod.EXPONENTIAL_SMOOTHING, alpha=D("0.5"))
    assert result.daily_demand == expected.daily_demand
    assert result.method == "exponential_smoothing"


def test_croston_and_seasonal_providers_are_registered():
    keys = {p.key for p in providers.available_providers()}
    assert {"croston", "seasonal"} <= keys


def test_croston_provider_matches_method():
    series = [D("0")] * 4 + [D("10")]  # one demand of 10 on the 5th day -> rate 2
    result = providers.get_provider("croston").generate(series, ForecastParams())
    expected = orchestrate(series, method=ForecastMethod.CROSTON)
    assert result.method == "croston"
    assert result.daily_demand == expected.daily_demand == D("2.0000")


def test_seasonal_provider_uses_period_and_horizon():
    series = [D("10") if i % 7 == 0 else D("1") for i in range(56)]
    params = ForecastParams(seasonal_period=7, horizon_days=30)
    result = providers.get_provider("seasonal").generate(series, params)
    assert result.method == "seasonal"
    assert result.daily_demand > D("0")


def test_register_and_replace_provider_is_isolated():
    class _Dummy(providers.ForecastProvider):
        key = "dummy_test_only"
        label = "Dummy"

        def generate(self, series, params):
            from app.forecast.domain.methods import package_result
            return package_result(series, Decimal("1"), ForecastMethod.MOVING_AVERAGE)

    try:
        providers.register_provider(_Dummy())
        assert providers.get_provider("dummy_test_only").label == "Dummy"
    finally:
        providers._REGISTRY.pop("dummy_test_only", None)  # keep global registry clean
