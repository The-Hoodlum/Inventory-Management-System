"""Pluggable forecast providers.

A *provider* turns a daily demand series into a ``ForecastResult`` using one
method. Providers register themselves in a registry keyed by a stable string, so
new methods are added by writing a class and calling ``register_provider`` — the
forecast service, API, and reorder engine all work through the registry and never
need to change.

Built-in providers (deterministic, no ML):
    moving_average          mean of the last N days
    exponential_smoothing   single exponential smoothing (recency-weighted)
    croston                 intermittent demand (size / interval smoothing)
    seasonal                classical seasonal decomposition (Holt-Winters family)

Future providers plug in the same way, e.g.::

    class MlProvider(ForecastProvider):
        key, label = "ml_xyz", "ML (xyz)"
        def generate(self, series, params): ...
    register_provider(MlProvider())

None of the existing code (service, API, reorder engine) changes when a provider is
added — selection flows through the registry and the demand-type / detection maps.
"""
from __future__ import annotations

import abc
from decimal import Decimal
from typing import ClassVar

from app.forecast.domain.exceptions import InvalidForecastInput
from app.forecast.domain.methods import (
    croston,
    moving_average,
    package_result,
    seasonal_point,
    single_exponential_smoothing,
)
from app.forecast.domain.models import ForecastMethod, ForecastParams, ForecastResult


class ForecastProvider(abc.ABC):
    """A forecasting method. Implementations are stateless and pure."""

    key: ClassVar[str]
    label: ClassVar[str]

    @abc.abstractmethod
    def generate(self, series: list[Decimal], params: ForecastParams) -> ForecastResult:
        """Produce a forecast from a dense, zero-filled daily series."""


class MovingAverageProvider(ForecastProvider):
    key = "moving_average"
    label = "Moving Average"

    def generate(self, series: list[Decimal], params: ForecastParams) -> ForecastResult:
        point = moving_average(series, params.ma_window)
        return package_result(series, point, ForecastMethod.MOVING_AVERAGE)


class ExponentialSmoothingProvider(ForecastProvider):
    key = "exponential_smoothing"
    label = "Exponential Smoothing"

    def generate(self, series: list[Decimal], params: ForecastParams) -> ForecastResult:
        point = single_exponential_smoothing(series, params.alpha)
        return package_result(series, point, ForecastMethod.EXPONENTIAL_SMOOTHING)


class CrostonProvider(ForecastProvider):
    """Intermittent-demand method — best for sparse, sporadic SKUs."""

    key = "croston"
    label = "Croston (intermittent)"

    def generate(self, series: list[Decimal], params: ForecastParams) -> ForecastResult:
        point = croston(series, params.croston_alpha)
        return package_result(series, point, ForecastMethod.CROSTON)


class SeasonalProvider(ForecastProvider):
    """Seasonal decomposition — best for SKUs with a recurring weekly/monthly cycle.
    Uses ``params.seasonal_period`` when set, otherwise auto-detects the period."""

    key = "seasonal"
    label = "Seasonal"

    def generate(self, series: list[Decimal], params: ForecastParams) -> ForecastResult:
        point = seasonal_point(
            series, period=params.seasonal_period, horizon_days=params.horizon_days
        )
        return package_result(series, point, ForecastMethod.SEASONAL)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, ForecastProvider] = {}


def register_provider(provider: ForecastProvider) -> None:
    """Register (or replace) a provider by its ``key``."""
    _REGISTRY[provider.key] = provider


def get_provider(key: str) -> ForecastProvider:
    provider = _REGISTRY.get(key)
    if provider is None:
        raise InvalidForecastInput(
            f"Unknown forecast provider '{key}'. Available: {sorted(_REGISTRY)}"
        )
    return provider


def available_providers() -> list[ForecastProvider]:
    return list(_REGISTRY.values())


def default_provider_key() -> str:
    return MovingAverageProvider.key


# Register the built-in deterministic providers on import.
register_provider(MovingAverageProvider())
register_provider(ExponentialSmoothingProvider())
register_provider(CrostonProvider())
register_provider(SeasonalProvider())
