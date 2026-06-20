"""Report assembly: fetch rows, delegate the math to ``app.reports.compute``
(pure, DB-free), and wrap the results into API schemas."""
from __future__ import annotations

import datetime as dt
import uuid

from app.reports import compute
from app.reports.repository import ReportsRepository
from app.reports.schemas import (
    AgingBucket,
    AgingItem,
    InventoryAgingReport,
    SupplierPerformanceReport,
    SupplierPerformanceRow,
)


class ReportsService:
    def __init__(self, repo: ReportsRepository) -> None:
        self.repo = repo

    async def get_inventory_aging(
        self, warehouse_id: uuid.UUID | None = None
    ) -> InventoryAgingReport:
        as_of = dt.datetime.now(dt.timezone.utc)
        products = await self.repo.product_lookup()  # id -> (sku, name, cost_price)
        movements = await self.repo.movements_for_aging(warehouse_id)

        costs = {pid: cost for pid, (_sku, _name, cost) in products.items()}
        result = compute.aging_from_movements(movements, costs, as_of)

        items: list[AgingItem] = []
        for it in result.items:
            sku, name, _cost = products.get(it.product_id, ("", "", None))
            items.append(
                AgingItem(
                    product_id=it.product_id,
                    sku=sku,
                    name=name,
                    warehouse_id=it.warehouse_id,
                    on_hand=it.on_hand,
                    cost_value=it.cost_value,
                    oldest_received_at=it.oldest_received_at,
                    bucket_qty=it.bucket_qty,
                )
            )
        buckets = [
            AgingBucket(
                label=b.label,
                min_days=b.min_days,
                max_days=b.max_days,
                qty=b.qty,
                cost_value=b.cost_value,
            )
            for b in result.buckets
        ]
        return InventoryAgingReport(as_of=as_of, buckets=buckets, items=items)

    async def get_supplier_performance(
        self, window_days: int | None = 365
    ) -> SupplierPerformanceReport:
        as_of = dt.datetime.now(dt.timezone.utc)
        since = as_of - dt.timedelta(days=window_days) if window_days else None

        suppliers = await self.repo.suppliers_basic()  # list of (id, name, lead_days)
        pos = await self.repo.pos_for_perf(since)
        line_totals = await self.repo.po_line_totals()
        timestamps = await self.repo.po_event_timestamps()

        calc = compute.supplier_performance(
            [sid for sid, _name, _lead in suppliers], pos, line_totals, timestamps
        )

        rows: list[SupplierPerformanceRow] = []
        for sid, name, lead_default in suppliers:
            c = calc[sid]
            rows.append(
                SupplierPerformanceRow(
                    supplier_id=sid,
                    supplier_name=name,
                    default_lead_time_days=lead_default,
                    po_count=c.po_count,
                    received_po_count=c.received_po_count,
                    on_time_po_count=c.on_time_po_count,
                    on_time_rate=c.on_time_rate,
                    avg_lead_time_days=c.avg_lead_time_days,
                    fill_rate=c.fill_rate,
                    last_order_at=c.last_order_at,
                )
            )

        rows.sort(key=lambda r: r.po_count, reverse=True)
        return SupplierPerformanceReport(as_of=as_of, window_days=window_days, suppliers=rows)
