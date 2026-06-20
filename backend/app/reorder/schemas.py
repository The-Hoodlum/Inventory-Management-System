"""API schemas for the reorder & procurement module."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReorderMethod = Literal["days_cover", "statistical"]
DemandMode = Literal["historical", "forecast"]


# --------------------------------- requests --------------------------------- #
class RunReorderRequest(BaseModel):
    """Parameters for a reorder evaluation run.

    Scope filters narrow which (product, warehouse) pairs are evaluated. The
    policy parameters supply defaults; per-product overrides
    (``products.reorder_point`` / ``products.safety_stock``) still take precedence.
    """

    warehouse_id: uuid.UUID | None = Field(default=None, description="Limit to one warehouse")
    category_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = Field(default=None, description="Limit to products of this primary supplier")
    window_days: int = Field(default=90, ge=1, le=730, description="Demand lookback window")
    review_period_days: Decimal = Field(default=Decimal("0"), ge=0)
    safety_days: Decimal = Field(default=Decimal("7"), ge=0)
    service_level: Decimal = Field(default=Decimal("0.95"), gt=0.5, lt=1)
    method: ReorderMethod = "days_cover"
    # Demand source for the average-daily-demand input. 'historical' uses the
    # window mean from sales_daily; 'forecast' runs a forecast provider over the
    # same series (and through the signal pipeline). Forecasting stays optional.
    demand_mode: DemandMode = "historical"
    forecast_method: str | None = Field(default=None, description="Provider key when demand_mode='forecast'")
    forecast_alpha: Decimal = Field(default=Decimal("0.3"), gt=0, le=1)
    forecast_ma_window: int | None = Field(default=None, ge=1)
    only_below_rop: bool = Field(default=True, description="Return only lines that need reordering")
    persist: bool = Field(default=True, description="Save actionable recommendations to the database")
    # Risk-aware procurement: fold active supply-chain intelligence into safety
    # stock, reorder point, and order timing. On by default; a no-op when there
    # is no intelligence affecting a SKU.
    risk_aware: bool = Field(default=True, description="Apply supply-chain risk to the recommendation")


class GeneratePurchaseOrdersRequest(BaseModel):
    recommendation_ids: list[uuid.UUID] = Field(min_length=1)
    notes: str | None = None
    expected_date: dt.date | None = None


# --------------------------------- responses -------------------------------- #
class ReorderLineResult(BaseModel):
    """One evaluated (product, warehouse) line from a run."""

    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    supplier_id: uuid.UUID | None

    avg_daily_demand: Decimal
    avg_monthly_sales: Decimal
    std_dev_daily: Decimal
    lead_time_days: Decimal
    review_period_days: Decimal
    units_per_carton: int
    moq: int

    safety_stock: Decimal
    safety_stock_method: str
    reorder_point: Decimal
    order_up_to_level: Decimal

    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    on_order: Decimal
    inventory_position: Decimal

    should_reorder: bool
    recommended_qty: Decimal
    recommended_cartons: int
    applied_moq: bool
    reason: str

    # Risk overlay (zero/empty when no intelligence applies to this SKU).
    risk_applied: bool = False
    risk_score: Decimal = Decimal("0")
    effective_lead_time_days: Decimal = Decimal("0")
    safety_stock_multiplier: Decimal = Decimal("1")
    expedite: bool = False
    risk_cost_impact: Decimal = Decimal("0")
    risk_drivers: list[str] = []

    recommendation_id: uuid.UUID | None = None


class ReorderRunResponse(BaseModel):
    generated_at: dt.datetime
    window_days: int
    evaluated: int
    to_order: int
    risk_affected: int = 0                     # SKUs whose recommendation was lifted by risk
    total_risk_cost_impact: Decimal = Decimal("0")  # added inventory investment from risk
    items: list[ReorderLineResult]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    supplier_id: uuid.UUID | None
    available_qty: Decimal
    on_order_qty: Decimal
    avg_daily_demand: Decimal
    reorder_point: Decimal
    safety_stock: Decimal
    recommended_qty: Decimal
    recommended_cartons: int
    status: str
    risk_score: Decimal = Decimal("0")
    lead_time_extra_days: Decimal = Decimal("0")
    risk_cost_impact: Decimal = Decimal("0")
    expedite: bool = False
    risk_drivers: list[str] | None = None
    generated_at: dt.datetime


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    ordered_qty: Decimal
    ordered_cartons: int | None
    unit_cost: Decimal
    line_total: Decimal
    received_qty: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    status: str
    currency: str
    fx_rate: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    notes: str | None
    expected_date: dt.date | None
    created_at: dt.datetime
    lines: list[PurchaseOrderLineOut] = []


class GeneratePurchaseOrdersResponse(BaseModel):
    created: int
    purchase_orders: list[PurchaseOrderOut]
    skipped_recommendation_ids: list[uuid.UUID] = []
