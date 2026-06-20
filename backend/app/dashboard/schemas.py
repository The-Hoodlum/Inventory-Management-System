"""Schemas for the read-only dashboard metrics endpoint."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class CatalogMetrics(BaseModel):
    products: int
    suppliers: int
    warehouses: int


class InventoryMetrics(BaseModel):
    total_on_hand: Decimal
    total_available: Decimal
    total_reserved: Decimal
    low_stock_count: int


class PurchaseOrderMetrics(BaseModel):
    by_status: dict[str, int]
    open_count: int      # approved + sent + partially_received
    open_value: Decimal  # value of those POs


class ActivityMetrics(BaseModel):
    receipts_last_30d: int


class DashboardMetrics(BaseModel):
    catalog: CatalogMetrics
    inventory: InventoryMetrics
    purchase_orders: PurchaseOrderMetrics
    activity: ActivityMetrics
    generated_at: dt.datetime
