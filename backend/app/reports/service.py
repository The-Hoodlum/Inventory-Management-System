"""Report assembly: fetch rows, delegate the math to ``app.reports.compute``
(pure, DB-free), and wrap the results into API schemas."""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

from app.reports import compute, sales_log
from app.reports.repository import ReportsRepository
from app.reports.schemas import (
    AgingBucket,
    AgingItem,
    InventoryAgingReport,
    SalesLogComponent,
    SalesLogReport,
    SalesLogRow,
    SalesLogTotals,
    StockPositionReport,
    StockPositionRow,
    SupplierPerformanceReport,
    SupplierPerformanceRow,
)


class ReportsService:
    def __init__(self, repo: ReportsRepository) -> None:
        self.repo = repo

    async def get_inventory_aging(
        self, warehouse_id: uuid.UUID | None = None
    ) -> InventoryAgingReport:
        as_of = dt.datetime.now(dt.UTC)
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

    async def get_stock_position(
        self, *, branch_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None,
        branch_ids: Sequence[uuid.UUID] | None = None,
    ) -> StockPositionReport:
        as_of = dt.datetime.now(dt.UTC)
        rows = await self.repo.stock_position(
            branch_id=branch_id, warehouse_id=warehouse_id, branch_ids=branch_ids
        )
        in_transit = await self.repo.in_transit_by_location(branch_id=branch_id, warehouse_id=warehouse_id)
        allowed = set(branch_ids) if branch_ids is not None else None

        merged: dict[tuple[uuid.UUID, uuid.UUID], StockPositionRow] = {}
        for r in rows:
            key = (r["location_id"], r["product_id"])
            merged[key] = StockPositionRow(
                branch_id=r["branch_id"], branch_name=r["branch_name"],
                location_id=r["location_id"], location_name=r["location_name"],
                product_id=r["product_id"], sku=r["sku"], name=r["name"],
                on_hand=r["on_hand"], reserved=r["reserved"], available=r["available"],
                in_transit=in_transit.get(key, Decimal("0")),
            )
        # In-transit toward a location that has no inventory row yet (first delivery).
        leftover = {k: v for k, v in in_transit.items() if k not in merged}
        if leftover:
            products = await self.repo.product_lookup()       # id -> (sku, name, cost)
            locations = await self.repo.locations_lookup()    # id -> (branch_id, loc_name, branch_name)
            for (loc_id, prod_id), qty in leftover.items():
                bid, loc_name, bname = locations.get(loc_id, (None, None, None))
                if branch_id is not None and bid != branch_id:
                    continue
                if allowed is not None and bid not in allowed:
                    continue
                sku, name, _cost = products.get(prod_id, (None, None, None))
                merged[(loc_id, prod_id)] = StockPositionRow(
                    branch_id=bid, branch_name=bname, location_id=loc_id, location_name=loc_name,
                    product_id=prod_id, sku=sku, name=name,
                    on_hand=Decimal("0"), reserved=Decimal("0"), available=Decimal("0"),
                    in_transit=qty,
                )
        result = sorted(
            merged.values(), key=lambda x: ((x.branch_name or ""), (x.location_name or ""), (x.name or ""))
        )
        return StockPositionReport(as_of=as_of, rows=result)

    async def get_sales_log(
        self, *, granularity: str, type_filter: str, branch_id: uuid.UUID | None,
        date_from: dt.date, date_to: dt.date, branch_ids: Sequence[uuid.UUID] | None = None,
    ) -> SalesLogReport:
        """THE shared sales aggregation (reused by any dashboard sales KPI): fetch parts
        + motorcycle sale events, bucket them by period with the pure no-double-count
        aggregator, and wrap into schemas."""
        events: list[sales_log.SaleEvent] = []
        # Parts events are needed for 'all' and 'parts'.
        if type_filter in (sales_log.TYPE_ALL, sales_log.TYPE_PARTS):
            for day, _branch, units, revenue in await self.repo.parts_sale_events(
                branch_id=branch_id, date_from=date_from, date_to=date_to, branch_ids=branch_ids
            ):
                events.append(sales_log.SaleEvent(day=day, kind=sales_log.PARTS, units=units, revenue=revenue))
        # Motorcycle events for 'all' and 'motorcycles'.
        if type_filter in (sales_log.TYPE_ALL, sales_log.TYPE_MOTORCYCLES):
            for day, _branch, revenue, historical in await self.repo.motorcycle_sale_events(
                branch_id=branch_id, date_from=date_from, date_to=date_to, branch_ids=branch_ids
            ):
                kind = sales_log.MOTO_HISTORICAL if historical else sales_log.MOTO_NEW
                events.append(sales_log.SaleEvent(day=day, kind=kind, units=Decimal("1"), revenue=revenue))

        rows_raw, totals_raw = sales_log.build_sales_log(
            events, granularity=granularity, type_filter=type_filter
        )
        rows = [
            SalesLogRow(
                period_start=r["period_start"], period_end=r["period_end"], label=r["label"],
                units=float(r["units"]), revenue=float(r["revenue"]),
                components=[
                    SalesLogComponent(type=c["type"], label=c["label"],
                                      units=float(c["units"]), revenue=float(c["revenue"]))
                    for c in r["components"]
                ],
            )
            for r in rows_raw
        ]
        by_kind = totals_raw["by_kind"]

        def _k(kind: str, field: str) -> float:
            return float(by_kind.get(kind, {}).get(field, 0))

        totals = SalesLogTotals(
            units=float(totals_raw["units"]), revenue=float(totals_raw["revenue"]),
            parts_units=_k(sales_log.PARTS, "units"), parts_revenue=_k(sales_log.PARTS, "revenue"),
            motorcycle_units=_k(sales_log.MOTO_NEW, "units"),
            motorcycle_revenue=_k(sales_log.MOTO_NEW, "revenue"),
            historical_units=_k(sales_log.MOTO_HISTORICAL, "units"),
            historical_revenue=_k(sales_log.MOTO_HISTORICAL, "revenue"),
        )
        return SalesLogReport(
            granularity=granularity, type=type_filter, branch_id=branch_id,
            date_from=date_from, date_to=date_to, rows=rows, totals=totals,
        )

    async def get_supplier_performance(
        self, window_days: int | None = 365
    ) -> SupplierPerformanceReport:
        as_of = dt.datetime.now(dt.UTC)
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
