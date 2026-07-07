"""Re-export all ORM models so they register on ``Base.metadata`` and can be
imported from a single place (e.g. ``from app.models import Product``)."""
from app.models.assistant import (
    AssistantConversation,
    AssistantMessage,
    UserWarehouseAccess,
    WhatsAppIdentity,
)
from app.models.bike_issue import BikeIssue, BikeIssueLine
from app.models.catalog import (
    Brand,
    Category,
    Product,
    Supplier,
    SupplierProduct,
)
from app.models.customer import Customer, CustomerAddress
from app.models.dispatch import (
    CustomerDelivery,
    CustomerDeliveryLine,
    DispatchNote,
    DispatchNoteLine,
    Issuance,
    IssuanceLine,
)
from app.models.identity import (
    AuditLog,
    Permission,
    RefreshSession,
    Role,
    RolePermission,
    Tenant,
    User,
    UserBranchAccess,
    UserRole,
)
from app.models.imports import ImportError, ImportFile, ImportJob, ImportMapping
from app.models.intelligence import IntelligenceSignal, SupplierScore
from app.models.inventory import (
    Branch,
    Inventory,
    InventoryReservation,
    StockMovement,
    Warehouse,
)
from app.models.motorcycle import (
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    MotorcycleUnitEvent,
    MotorcycleVariant,
)
from app.models.order_request import (
    RequestAudit,
    RequestHeader,
    RequestLine,
    StockTransferLedger,
)
from app.models.procurement import (
    DemandForecast,
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    ReorderRecommendation,
    SalesDaily,
)
from app.models.sales import (
    CreditNote,
    CreditNoteLine,
    DeliveryNote,
    DeliveryNoteLine,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
    Receipt,
    Return,
    ReturnLine,
    SalesOrder,
    SalesOrderLine,
)

__all__ = [
    "Tenant", "User", "UserBranchAccess", "Role", "Permission", "RolePermission", "UserRole",
    "AuditLog", "RefreshSession", "Category", "Brand", "Supplier", "Product", "SupplierProduct",
    "Branch", "Warehouse", "Inventory", "InventoryReservation", "StockMovement",
    "SalesDaily", "PurchaseOrder", "PurchaseOrderLine", "ReorderRecommendation",
    "PurchaseOrderEvent", "DemandForecast", "IntelligenceSignal", "SupplierScore",
    "ImportJob", "ImportFile", "ImportError", "ImportMapping",
    "AssistantConversation", "AssistantMessage", "UserWarehouseAccess", "WhatsAppIdentity",
    "RequestHeader", "RequestLine", "RequestAudit", "StockTransferLedger",
    "Customer", "CustomerAddress",
    "Quotation", "QuotationLine", "SalesOrder", "SalesOrderLine",
    "DeliveryNote", "DeliveryNoteLine", "Invoice", "InvoiceLine",
    "Payment", "PaymentAllocation", "Receipt",
    "Return", "ReturnLine", "CreditNote", "CreditNoteLine",
    "MotorcycleModel", "MotorcycleVariant", "MotorcycleColour",
    "MotorcycleUnit", "MotorcycleUnitEvent",
    "DispatchNote", "DispatchNoteLine",
    "Issuance", "IssuanceLine",
    "CustomerDelivery", "CustomerDeliveryLine",
    "BikeIssue", "BikeIssueLine",
]
