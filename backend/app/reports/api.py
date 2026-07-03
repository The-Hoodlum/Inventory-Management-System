"""Reports API: inventory aging, supplier performance, and the unified sales log
(read-only)."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_reports_service, require_permission
from app.core.exceptions import BusinessRuleError
from app.core.permissions import P
from app.reports import sales_log
from app.reports.schemas import (
    InventoryAgingReport,
    SalesLogReport,
    StockPositionReport,
    SupplierPerformanceReport,
)
from app.reports.service import ReportsService

router = APIRouter()


@router.get("/sales-log", response_model=SalesLogReport)
async def sales_log_report(
    granularity: str = Query(default="daily"),
    type: str = Query(default="all"),
    branch_id: uuid.UUID | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    _: CurrentUser = Depends(require_permission(P.REPORT_READ)),
    svc: ReportsService = Depends(get_reports_service),
) -> SalesLogReport:
    """Unified sales log: parts + motorcycle revenue bucketed daily / weekly / monthly,
    filterable by type (all | parts | motorcycles), branch and date range. One shared
    no-double-count aggregation (see app/reports/sales_log.py)."""
    if granularity not in sales_log.GRANULARITIES:
        raise BusinessRuleError("granularity must be daily, weekly or monthly.")
    if type not in sales_log.TYPE_FILTERS:
        raise BusinessRuleError("type must be all, parts or motorcycles.")
    today = dt.date.today()
    # Default to the last ~12 weeks when no range is given.
    date_to = date_to or today
    date_from = date_from or (date_to - dt.timedelta(days=84))
    if date_from > date_to:
        raise BusinessRuleError("date_from must not be after date_to.")
    return await svc.get_sales_log(
        granularity=granularity, type_filter=type, branch_id=branch_id,
        date_from=date_from, date_to=date_to,
    )


@router.get("/stock-position", response_model=StockPositionReport)
async def stock_position(
    branch_id: uuid.UUID | None = Query(default=None),
    warehouse_id: uuid.UUID | None = Query(default=None),
    _: CurrentUser = Depends(require_permission(P.REPORT_READ)),
    svc: ReportsService = Depends(get_reports_service),
) -> StockPositionReport:
    # On-hand / reserved / available / in-transit per branch + location + product.
    return await svc.get_stock_position(branch_id=branch_id, warehouse_id=warehouse_id)


@router.get("/inventory-aging", response_model=InventoryAgingReport)
async def inventory_aging(
    warehouse_id: uuid.UUID | None = Query(default=None),
    _: CurrentUser = Depends(require_permission(P.REPORT_READ)),
    svc: ReportsService = Depends(get_reports_service),
) -> InventoryAgingReport:
    return await svc.get_inventory_aging(warehouse_id=warehouse_id)


@router.get("/supplier-performance", response_model=SupplierPerformanceReport)
async def supplier_performance(
    window_days: int = Query(default=365, ge=1, le=3650),
    _: CurrentUser = Depends(require_permission(P.REPORT_READ)),
    svc: ReportsService = Depends(get_reports_service),
) -> SupplierPerformanceReport:
    return await svc.get_supplier_performance(window_days=window_days)
