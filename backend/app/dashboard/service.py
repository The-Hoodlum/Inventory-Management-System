"""Dashboard service: assemble KPI metrics from the aggregation repository."""
from __future__ import annotations

import datetime as dt

from app.dashboard.repository import DashboardRepository
from app.dashboard.schemas import (
    ActivityMetrics,
    CatalogMetrics,
    DashboardMetrics,
    InventoryMetrics,
    PurchaseOrderMetrics,
)


class DashboardService:
    def __init__(self, repo: DashboardRepository) -> None:
        self.repo = repo

    async def get_metrics(self) -> DashboardMetrics:
        products = await self.repo.count_active_products()
        suppliers = await self.repo.count_active_suppliers()
        warehouses = await self.repo.count_active_warehouses()

        on_hand, available, reserved = await self.repo.inventory_totals()
        low_stock = await self.repo.low_stock_count()

        by_status = await self.repo.po_status_counts()
        open_count, open_value = await self.repo.open_purchase_orders()

        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=30)
        receipts = await self.repo.receipts_since(since)

        return DashboardMetrics(
            catalog=CatalogMetrics(products=products, suppliers=suppliers, warehouses=warehouses),
            inventory=InventoryMetrics(
                total_on_hand=on_hand,
                total_available=available,
                total_reserved=reserved,
                low_stock_count=low_stock,
            ),
            purchase_orders=PurchaseOrderMetrics(
                by_status=by_status, open_count=open_count, open_value=open_value
            ),
            activity=ActivityMetrics(receipts_last_30d=receipts),
            generated_at=dt.datetime.now(dt.UTC),
        )
