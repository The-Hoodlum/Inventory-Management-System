"""Reports API: inventory aging, supplier performance, and the unified sales log
(read-only)."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import (
    CurrentUser,
    get_reports_service,
    require_permission,
    resolve_branch_scope,
)
from app.core.exceptions import BusinessRuleError
from app.core.permissions import P
from app.reports import sales_log
from app.reports.schemas import (
    InventoryAgingReport,
    SalesLogReport,
    SalesSummaryReport,
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
    user: CurrentUser = Depends(require_permission(P.REPORT_READ)),
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
    # Scope to the caller's branch(es) — a multi-branch user sees ALL of theirs, a specific
    # (allowed) branch when asked, 403 on a disallowed one, all branches when unrestricted.
    return await svc.get_sales_log(
        granularity=granularity, type_filter=type, branch_id=None,
        branch_ids=resolve_branch_scope(user, branch_id),
        date_from=date_from, date_to=date_to,
    )


@router.get("/sales-summary", response_model=SalesSummaryReport)
async def sales_summary(
    period: str = Query(default="daily"),
    date: dt.date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.REPORT_READ)),
    svc: ReportsService = Depends(get_reports_service),
) -> SalesSummaryReport:
    """Daily / monthly sales report (invoiced transactions, frozen ZMW): line detail +
    payment breakdown by method + totals, scoped to the caller's branch(es)."""
    if period not in ("daily", "monthly"):
        raise BusinessRuleError("period must be daily or monthly.")
    return await svc.get_sales_summary(
        period=period, on=date or dt.date.today(),
        branch_ids=resolve_branch_scope(user, branch_id),
    )


@router.get("/stock-position", response_model=StockPositionReport)
async def stock_position(
    branch_id: uuid.UUID | None = Query(default=None),
    warehouse_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.REPORT_READ)),
    svc: ReportsService = Depends(get_reports_service),
) -> StockPositionReport:
    # On-hand / reserved / available / in-transit per branch + location + product,
    # scoped to the caller's branch(es).
    return await svc.get_stock_position(
        branch_ids=resolve_branch_scope(user, branch_id), warehouse_id=warehouse_id
    )


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
