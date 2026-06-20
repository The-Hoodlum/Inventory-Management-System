"""Re-export all ORM models so they register on ``Base.metadata`` and can be
imported from a single place (e.g. ``from app.models import Product``)."""
from app.models.catalog import (
    Brand,
    Category,
    Product,
    Supplier,
    SupplierProduct,
)
from app.models.identity import (
    AuditLog,
    Permission,
    RefreshSession,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
)
from app.models.imports import ImportError, ImportFile, ImportJob, ImportMapping
from app.models.intelligence import IntelligenceSignal, SupplierScore
from app.models.inventory import Inventory, StockMovement, Warehouse
from app.models.procurement import (
    DemandForecast,
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    ReorderRecommendation,
    SalesDaily,
)

__all__ = [
    "Tenant", "User", "Role", "Permission", "RolePermission", "UserRole",
    "AuditLog", "RefreshSession", "Category", "Brand", "Supplier", "Product", "SupplierProduct",
    "Warehouse", "Inventory", "StockMovement",
    "SalesDaily", "PurchaseOrder", "PurchaseOrderLine", "ReorderRecommendation",
    "PurchaseOrderEvent", "DemandForecast", "IntelligenceSignal", "SupplierScore",
    "ImportJob", "ImportFile", "ImportError", "ImportMapping",
]
