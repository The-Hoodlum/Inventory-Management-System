"""Branch order-request (requisition) module: cashier raises -> admin approves -> issues.

Thin clean-architecture feature module (domain -> repository -> service -> api). Inventory
is deducted only at issue time; every transition is audited. Tenant-scoped via RLS.
"""
