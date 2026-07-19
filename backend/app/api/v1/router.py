"""Aggregate router for API v1."""
from __future__ import annotations

from fastapi import APIRouter

from app.advisor.api import router as advisor_router
from app.api.v1.endpoints import (
    auth,
    branches,
    customers,
    inventory,
    products,
    suppliers,
    tenant,
    users,
    warehouses,
)
from app.assembly.api import router as assembly_router
from app.assistant.api import router as assistant_router
from app.bike_issues.api import router as bike_issues_router
from app.container.api import router as container_router
from app.customer_delivery.api import router as customer_delivery_router
from app.dashboard.api import router as dashboard_router
from app.demand.api import router as demand_router
from app.dispatch.api import router as dispatch_router
from app.finance.api import router as finance_router
from app.forecast.api import router as forecast_router
from app.imports.api import router as imports_router
from app.integrations.whatsapp.router import router as whatsapp_router
from app.intelligence.api import router as intelligence_router
from app.issuance.api import router as issuance_router
from app.motorcycles.api import router as motorcycles_router
from app.notifications.api import router as notifications_router
from app.order_requests.api import router as order_requests_router
from app.procurement.api import router as procurement_router
from app.reorder.api import purchase_order_router, reorder_router
from app.reports.api import router as reports_router
from app.sales.api import router as sales_router
from app.search.api import router as search_router
from app.service_followup.api import router as service_followup_router

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
api_router.include_router(branches.router, prefix="/branches", tags=["branches"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
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
api_router.include_router(sales_router, prefix="/sales", tags=["sales"])
api_router.include_router(motorcycles_router, prefix="/motorcycles", tags=["motorcycles"])
api_router.include_router(bike_issues_router, prefix="/bike-issues", tags=["bike-issues"])
api_router.include_router(assembly_router, prefix="/assembly", tags=["assembly"])
api_router.include_router(
    service_followup_router, prefix="/service-followup", tags=["service-followup"]
)
api_router.include_router(dispatch_router, prefix="/delivery-notes", tags=["delivery-notes"])
api_router.include_router(issuance_router, prefix="/issuances", tags=["issuances"])
api_router.include_router(customer_delivery_router, prefix="/customer-deliveries", tags=["customer-deliveries"])
api_router.include_router(search_router, prefix="/search", tags=["search"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(finance_router, prefix="/finance", tags=["finance"])
