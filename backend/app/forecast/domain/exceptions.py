"""Forecast-domain errors (pure; no framework dependencies)."""
from __future__ import annotations


class ForecastError(ValueError):
    """Base class for forecast-domain errors."""


class InvalidForecastInput(ForecastError):
    """Raised for malformed inputs (bad window, alpha out of range, etc.)."""
