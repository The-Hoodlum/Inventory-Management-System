"""API schemas for the forecast module."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------- requests --------------------------------- #
class ForecastRunRequest(BaseModel):
    """Generate (and persist) forecasts for a warehouse.

    With ``product_id`` set, forecasts that one product; omit it to forecast every
    active product in the warehouse. ``method`` is a provider key (see GET
    /forecast/providers); omitted uses the default provider.
    """

    warehouse_id: uuid.UUID
    product_id: uuid.UUID | None = None
    method: str | None = Field(
        default=None,
        description="Provider key (see GET /forecast/providers); 'auto' detects the "
        "best method per product; default provider if omitted",
    )
    window_days: int = Field(default=90, ge=1, le=1830)
    horizon_days: int = Field(default=30, ge=1, le=365)
    ma_window: int | None = Field(default=None, ge=1, description="Moving-average lookback")
    alpha: Decimal = Field(default=Decimal("0.3"), gt=0, le=1, description="Exp-smoothing weight")
    croston_alpha: Decimal = Field(default=Decimal("0.1"), gt=0, le=1, description="Croston weight")
    seasonal_period: int | None = Field(
        default=None, ge=2, le=365, description="Seasonal cycle length; auto-detected if omitted"
    )
    as_of: dt.date | None = Field(default=None, description="Anchor date (defaults to today)")


class DemandAnalyzeRequest(BaseModel):
    """Measure a (product, warehouse) demand series without persisting a forecast —
    returns its detected pattern and the suggested demand_type / forecast method."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    window_days: int = Field(default=90, ge=2, le=1830)
    as_of: dt.date | None = Field(default=None, description="Anchor date (defaults to today)")


# --------------------------------- responses -------------------------------- #
class ProviderOut(BaseModel):
    key: str
    label: str


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    method: str
    window_days: int
    horizon_days: int
    forecast_date: dt.date
    daily_demand: Decimal
    adjusted_daily_demand: Decimal
    std_dev_daily: Decimal
    confidence: Decimal
    risk_score: Decimal
    observations: int
    days_with_demand: int
    total_demand: Decimal
    generated_at: dt.datetime


class ForecastRunResponse(BaseModel):
    method: str
    warehouse_id: uuid.UUID
    generated: int
    forecasts: list[ForecastOut]


class ForecastAccuracyResponse(BaseModel):
    forecast_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    method: str
    forecast_date: dt.date
    horizon_days: int
    evaluated_days: int                 # days with actuals available so far
    mae: Decimal | None
    bias: Decimal | None
    rmse: Decimal | None
    mape: Decimal | None
    mape_points: int


class ForecastSummaryResponse(BaseModel):
    total_forecasts: int                # all rows ever generated (this tenant)
    pairs_forecasted: int               # distinct (product, warehouse) with a forecast
    avg_confidence: Decimal | None
    avg_risk_score: Decimal | None
    high_risk_count: int                # latest forecasts with risk_score >= 0.5
    by_method: dict[str, int]
    recent: list[ForecastOut]
    generated_at: dt.datetime


class DemandPatternResponse(BaseModel):
    """Explainable, measured description of a demand series (see domain/patterns)."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    window_days: int
    as_of: dt.date
    observations: int                   # daily buckets in the window
    days_with_demand: int               # buckets with quantity > 0
    adi: Decimal | None                 # average demand interval (None = no demand)
    cv_squared: Decimal | None          # CV² of non-zero sizes (None = < 2 occurrences)
    classification: str                 # smooth | erratic | intermittent | lumpy
    trend_direction: str                # up | down | flat
    trend_slope: Decimal                # units/day
    trend_strength: Decimal             # 0..1
    seasonal: bool
    seasonal_period: int | None         # detected cycle length in days
    seasonal_strength: Decimal          # 0..1 autocorrelation at the period
    suggested_demand_type: str | None   # DemandType vocabulary, or None when no demand
    suggested_method: str               # forecast-provider key
    drivers: list[str]                  # human-readable explanations
