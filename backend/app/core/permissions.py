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
    ORDER_REQUEST_CREATE = "order_request.create"   # branch user/cashier raises a restock/sales request
    ORDER_REQUEST_TRANSFER = "order_request.transfer"  # stock manager raises an inter-location transfer
    ORDER_REQUEST_READ = "order_request.read"       # view requests (own branch or, for admin, all)
    ORDER_REQUEST_APPROVE = "order_request.approve"  # approve / partially approve / reject
    ORDER_REQUEST_ISSUE = "order_request.issue"     # issue stock (deducts inventory)
    ORDER_REQUEST_RECEIVE = "order_request.receive"  # capture receipt (received/missing/damaged/extra)
    ORDER_REQUEST_COMPLETE = "order_request.complete"  # confirm receipt + close (complete)
    # Sales & Distribution (quotation -> sales order -> delivery -> invoice -> payment -> receipt; POS)
    CUSTOMER_READ = "customer.read"
    CUSTOMER_MANAGE = "customer.manage"
    SALES_READ = "sales.read"
    SALES_QUOTE = "sales.quote"        # create/send/convert quotations
    SALES_ORDER = "sales.order"        # create/confirm sales orders (reserves stock)
    SALES_DELIVER = "sales.deliver"    # issue delivery notes (deducts inventory)
    SALES_INVOICE = "sales.invoice"    # create/send invoices
    SALES_PAYMENT = "sales.payment"    # record payments + issue receipts
    SALES_MANAGE = "sales.manage"      # approve discounts, cancel, override
    SALES_RETURN = "sales.return"      # process customer returns + credit notes
    POS_USE = "pos.use"                # operate the POS fast-sale checkout
    # Motorcycle module (serialized-asset catalog + per-unit lifecycle registry)
    MOTORCYCLE_READ = "motorcycle.read"      # view units + reference catalog
    MOTORCYCLE_MANAGE = "motorcycle.manage"  # create/update units + drive lifecycle (reserve/sell/transfer)
    MOTORCYCLE_CONFIG = "motorcycle.config"  # manage reference catalog (models/variants/colours)
    # Delivery / dispatch notes (typed) — paper that documents a stock movement.
    DELIVERY_NOTE_READ = "delivery_note.read"
    DELIVERY_NOTE_DISPATCH = "delivery_note.dispatch"  # create + dispatch (send in transit)
    DELIVERY_NOTE_RECEIVE = "delivery_note.receive"    # confirm receipt (with discrepancies)
