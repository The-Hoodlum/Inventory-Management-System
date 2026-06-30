"""Aggregate router for API v1."""
from __future__ import annotations

from fastapi import APIRouter

from app.advisor.api import router as advisor_router
from app.api.v1.endpoints import (
    auth,
    branches,
    inventory,
    products,
    suppliers,
    tenant,
    users,
    warehouses,
)
from app.assistant.api import router as assistant_router
from app.container.api import router as container_router
from app.dashboard.api import router as dashboard_router
from app.demand.api import router as demand_router
from app.forecast.api import router as forecast_router
from app.imports.api import router as imports_router
from app.integrations.whatsapp.router import router as whatsapp_router
from app.intelligence.api import router as intelligence_router
from app.order_requests.api import router as order_requests_router
from app.procurement.api import router as procurement_router
from app.reorder.api import purchase_order_router, reorder_router
from app.reports.api import router as reports_router

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
api_router.include_router(branches.router, prefix="/branches", tags=["branches"])
api_router.include_router(warehouses.router, prefix="/warehouses", tags=["warehouses"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(reorder_router, prefix="/reorder", tags=["reorder"])
api_router.include_router(
    purchase_order_router, prefix="/reorder/purchase-orders", tags=["reorder"]
)
api_router.include_router(procurement_router, prefix="/purchase-orders", tags=["procurement"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(demand_router, prefix="/demand", tags=["demand"])
api_router.include_router(forecast_router, prefix="/forecast", tags=["forecast"])
api_router.include_router(container_router, prefix="/container", tags=["container"])
api_router.include_router(advisor_router, prefix="/advisor", tags=["advisor"])
api_router.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
api_router.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
api_router.include_router(imports_router, prefix="/imports", tags=["imports"])
api_router.include_router(intelligence_router, prefix="/intelligence", tags=["intelligence"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(tenant.router, prefix="/tenant", tags=["tenant"])
api_router.include_router(order_requests_router, prefix="/order-requests", tags=["order-requests"])
