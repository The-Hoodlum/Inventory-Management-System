"""Permission codes. These mirror exactly the codes seeded in
``database/sql/seed_rbac.sql`` and checked by the ``require_permission`` dependency.
"""
from __future__ import annotations


class P:
    # Products
    PRODUCT_READ = "product.read"
    PRODUCT_CREATE = "product.create"
    PRODUCT_UPDATE = "product.update"
    PRODUCT_DELETE = "product.delete"
    # Suppliers
    SUPPLIER_READ = "supplier.read"
    SUPPLIER_CREATE = "supplier.create"
    SUPPLIER_UPDATE = "supplier.update"
    # Warehouses
    WAREHOUSE_MANAGE = "warehouse.manage"
    # Inventory
    INVENTORY_READ = "inventory.read"
    INVENTORY_RECEIVE = "inventory.receive"
    INVENTORY_ISSUE = "inventory.issue"
    INVENTORY_ADJUST = "inventory.adjust"
    INVENTORY_TRANSFER = "inventory.transfer"
    # Reorder
    REORDER_READ = "reorder.read"
    REORDER_RUN = "reorder.run"
    REORDER_MANAGE = "reorder.manage"
    # Purchase orders
    PO_READ = "po.read"
    PO_CREATE = "po.create"
    PO_UPDATE = "po.update"
    PO_APPROVE = "po.approve"
    # Reports / admin
    REPORT_READ = "report.read"
    REPORT_EXPORT = "report.export"
    USER_MANAGE = "user.manage"
    SETTINGS_MANAGE = "settings.manage"
    DASHBOARD_READ = "dashboard.read"
    # Data import (generic spreadsheet import framework)
    DATA_IMPORT = "data.import"
    # Conversational assistant (WhatsApp / API)
    ASSISTANT_USE = "assistant.use"
    # Branch order requests (requisitions)
    ORDER_REQUEST_CREATE = "order_request.create"   # branch user/cashier raises a request
    ORDER_REQUEST_READ = "order_request.read"       # view requests (own branch or, for admin, all)
    ORDER_REQUEST_APPROVE = "order_request.approve"  # approve / partially approve / reject
    ORDER_REQUEST_ISSUE = "order_request.issue"     # issue stock (deducts inventory)
    ORDER_REQUEST_RECEIVE = "order_request.receive"  # capture receipt (received/missing/damaged/extra)
    ORDER_REQUEST_COMPLETE = "order_request.complete"  # confirm receipt + close (complete)
