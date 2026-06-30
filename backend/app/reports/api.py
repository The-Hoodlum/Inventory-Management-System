"""Reports API: inventory aging and supplier performance (read-only)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_reports_service, require_permission
from app.core.permissions import P
from app.reports.schemas import (
    InventoryAgingReport,
    StockPositionReport,
    SupplierPerformanceReport,
)
from app.reports.service import ReportsService

router = APIRouter()


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
