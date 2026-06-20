"""API schemas for the intelligence module."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["freight", "port", "commodity", "trade", "supplier", "geopolitical"]
ScopeType = Literal["global", "country", "supplier", "commodity", "route", "port"]


# --------------------------------- requests --------------------------------- #
class ManualSignalRequest(BaseModel):
    """Analyst-entered intelligence observation (source='manual')."""

    category: Category
    scope_type: ScopeType = "global"
    scope_key: str | None = None
    severity: Decimal = Field(ge=0, le=1)
    demand_factor: Decimal = Field(default=Decimal("1"), gt=0)
    confidence: Decimal = Field(default=Decimal("0.7"), ge=0, le=1)
    headline: str = Field(min_length=1)
    value: Decimal | None = None
    unit: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    expires_at: dt.datetime | None = None
    detail: dict | None = None


class IngestRequest(BaseModel):
    """Run ingestion providers. Empty = all providers."""

    categories: list[Category] = Field(default_factory=list)


class PipelineImpactRequest(BaseModel):
    base_daily_demand: Decimal = Field(default=Decimal("100"), ge=0)
    supplier_id: uuid.UUID | None = None


# --------------------------------- responses -------------------------------- #
class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    scope_type: str
    scope_key: str | None
    severity: Decimal
    demand_factor: Decimal
    confidence: Decimal
    headline: str
    value: Decimal | None
    unit: str | None
    trend: str | None
    source: str
    observed_at: dt.datetime
    expires_at: dt.datetime | None


class IngestResponse(BaseModel):
    ingested: int
    by_category: dict[str, int]
    by_source: dict[str, int]


class IntelligenceDashboardResponse(BaseModel):
    risk_score: Decimal                  # 0..1 overall supply risk
    forecast_impact: Decimal             # composite demand factor (1.0 = no change)
    confidence: Decimal                  # 0..1
    active_signals: int
    by_category: dict[str, Decimal]      # category -> risk contribution
    recommended_actions: list[str]
    drivers: list[str]                   # top signal headlines
    generated_at: dt.datetime


class PipelineImpactResponse(BaseModel):
    """Proves the providers feed the forecast SignalPipeline: runs the registered
    pipeline over a base demand with the current intelligence snapshot."""

    supplier_id: uuid.UUID | None
    base_daily_demand: Decimal
    adjusted_daily_demand: Decimal
    risk_score: Decimal
    applied: list[str]                   # signal reasons applied by the pipeline


# ----------------------------- supplier scores ------------------------------ #
class SupplierScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str
    on_time_rate: Decimal | None
    avg_lead_time_days: Decimal | None
    lead_time_stdev_days: Decimal | None
    lead_time_accuracy: Decimal | None
    fill_rate: Decimal | None
    delivery_performance: Decimal | None
    reliability: Decimal
    performance_risk: Decimal
    intelligence_risk: Decimal
    risk_score: Decimal
    grade: str
    po_count: int
    received_po_count: int
    total_spend: Decimal
    last_order_at: dt.datetime | None
    drivers: list[str] | None
    computed_at: dt.datetime


class SupplierScoreRefreshResponse(BaseModel):
    scored: int
    generated_at: dt.datetime


class SupplierScoreDetail(BaseModel):
    latest: SupplierScoreOut
    history: list[SupplierScoreOut]
