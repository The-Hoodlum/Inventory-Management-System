"""Schemas for read-only analytical reports: inventory aging and supplier
performance. Decimal fields serialize as strings (consistent with the rest of
the API), rates are plain floats in the 0–1 range."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel


# ------------------------------ inventory aging ----------------------------- #
class AgingBucket(BaseModel):
    label: str
    min_days: int
    max_days: int | None  # None == open-ended (the 90+ bucket)
    qty: Decimal
    cost_value: Decimal


class AgingItem(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    on_hand: Decimal
    cost_value: Decimal
    oldest_received_at: dt.datetime | None
    bucket_qty: dict[str, Decimal]  # bucket label -> remaining qty in that band


class InventoryAgingReport(BaseModel):
    as_of: dt.datetime
    buckets: list[AgingBucket]
    items: list[AgingItem]


# --------------------------- supplier performance --------------------------- #
class SupplierPerformanceRow(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    default_lead_time_days: int
    po_count: int
    received_po_count: int
    on_time_po_count: int
    # Rates are None when there is no eligible denominator yet.
    on_time_rate: float | None         # received POs that arrived on/before expected date
    avg_lead_time_days: float | None   # sent (or created) -> received, in days
    fill_rate: float | None            # received_qty / ordered_qty across active POs
    last_order_at: dt.datetime | None


class SupplierPerformanceReport(BaseModel):
    as_of: dt.datetime
    window_days: int | None
    suppliers: list[SupplierPerformanceRow]


# ----------------------- stock position (by branch/location) ---------------- #
class StockPositionRow(BaseModel):
    branch_id: uuid.UUID | None
    branch_name: str | None
    location_id: uuid.UUID
    location_name: str | None
    product_id: uuid.UUID
    sku: str | None
    name: str | None
    on_hand: Decimal
    reserved: Decimal
    available: Decimal       # on_hand - reserved - damaged
    in_transit: Decimal      # issued-but-not-yet-received transfers inbound to this location


class StockPositionReport(BaseModel):
    as_of: dt.datetime
    rows: list[StockPositionRow]


# ------------------------------- sales log ---------------------------------- #
class SalesLogComponent(BaseModel):
    """A single sale type's contribution within a period (the drill-down breakdown).
    ``type`` is one of parts / motorcycle_new / motorcycle_historical."""
    type: str
    label: str
    units: float
    revenue: float


class SalesLogRow(BaseModel):
    period_start: dt.date
    period_end: dt.date
    label: str
    units: float
    revenue: float
    components: list[SalesLogComponent] = []


class SalesLogTotals(BaseModel):
    units: float
    revenue: float
    parts_units: float = 0.0
    parts_revenue: float = 0.0
    motorcycle_units: float = 0.0        # live serialized-unit sales
    motorcycle_revenue: float = 0.0
    historical_units: float = 0.0        # imported historical sold units
    historical_revenue: float = 0.0


class SalesLogReport(BaseModel):
    """Unified sales log — parts + motorcycles bucketed by period, filtered by type,
    branch and date range. Revenue is summed in stored amounts (no FX conversion:
    parts and motorcycles may be priced in different currencies)."""
    granularity: str          # daily | weekly | monthly
    type: str                 # all | parts | motorcycles
    branch_id: uuid.UUID | None
    date_from: dt.date
    date_to: dt.date
    rows: list[SalesLogRow]
    totals: SalesLogTotals
