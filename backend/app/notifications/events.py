"""Event-type identifiers for notifications. Producers pass these to the service; they're
generic strings (the core knows nothing about assembly) but named here so producers stay
consistent and the set is discoverable."""
from __future__ import annotations

# Assembly (first producers — sell-before-assembly feature)
BIKE_SOLD_BEFORE_ASSEMBLY = "bike.sold_before_assembly"
BIKE_ASSEMBLED = "bike.assembled"
BIKE_DISPATCHED_UNASSEMBLED = "bike.dispatched_unassembled"

# Sales — a completed motorcycle sale, pushed to the branch's managers in real time.
BIKE_SOLD = "bike.sold"

# Approvals & inventory (event versions of the computed bell signals)
ORDER_REQUEST_PENDING = "order_request.pending"      # a requisition awaits approval
PO_PENDING_APPROVAL = "po.pending_approval"          # a purchase order awaits approval
INVENTORY_LOW_STOCK = "inventory.low_stock"          # an item just crossed its reorder point
