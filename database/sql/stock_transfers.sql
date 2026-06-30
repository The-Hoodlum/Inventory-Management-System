-- ============================================================================
--  Stock transfers — full engine on the order-request tables (additive, idempotent)
--
--  A transfer is an order-request that moves stock from a SOURCE location to a
--  DESTINATION location (both are warehouses; the branch is each location's
--  warehouses.branch_id). This script extends the request tables to the full
--  transfer lifecycle:
--
--    • new statuses: draft, partially_issued, in_transit, partially_received, received
--    • new transfer types: internal_transfer, damaged_replacement
--    • receipt: received_by / received_date on the header
--    • per line: extra_qty + the reconciliation invariant
--          received_qty + missing_qty + damaged_qty = issued_qty + extra_qty
--    • the order_request.receive permission (capture a receipt)
--
--  Reservations (hold on approval, consume on issue, release on cancel/reject) reuse
--  the inventory_reservations table. Generic + industry-agnostic. Idempotent.
-- ============================================================================

-- 1) Full status set (recreate the inline CHECK).
ALTER TABLE request_headers DROP CONSTRAINT IF EXISTS request_headers_status_check;
ALTER TABLE request_headers ADD CONSTRAINT request_headers_status_check
    CHECK (status IN (
        'draft','pending','approved','partially_approved','rejected',
        'partially_issued','issued','in_transit','partially_received','received',
        'cancelled','completed'));

-- 2) Full transfer-type set (recreate the inline CHECK).
ALTER TABLE request_headers DROP CONSTRAINT IF EXISTS request_headers_purpose_check;
ALTER TABLE request_headers ADD CONSTRAINT request_headers_purpose_check
    CHECK (purpose IN (
        'for_sale','shelf_replenishment','internal_transfer','branch_transfer',
        'workshop_use','damaged_replacement','office_use','stock_adjustment','other'));

-- 3) Receipt confirmation on the header (set on the -> received transition).
ALTER TABLE request_headers ADD COLUMN IF NOT EXISTS received_by   UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE request_headers ADD COLUMN IF NOT EXISTS received_date TIMESTAMPTZ;

-- 4) Per-line "extra" (received MORE than issued) + the reconciliation invariant.
ALTER TABLE request_lines ADD COLUMN IF NOT EXISTS extra_qty NUMERIC(18,4) CHECK (extra_qty >= 0);

ALTER TABLE request_lines DROP CONSTRAINT IF EXISTS request_lines_reconcile_check;
ALTER TABLE request_lines ADD CONSTRAINT request_lines_reconcile_check
    CHECK (
        received_qty IS NULL
        OR received_qty + COALESCE(missing_qty, 0) + COALESCE(damaged_qty, 0)
           = issued_qty + COALESCE(extra_qty, 0)
    );

-- 5) Permission to capture a receipt (reconcile a transfer). Per the transfer
--    permission model this is a stock-manager action — the request user (Cashier)
--    can create and view, but NOT approve / issue / receive / complete.
INSERT INTO permissions (code, description) VALUES
    ('order_request.receive', 'Capture receipt (received/missing/damaged/extra) for an issued transfer')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'order_request.receive'
WHERE r.is_system AND r.name IN ('Admin','Warehouse Manager','Branch Manager')
ON CONFLICT DO NOTHING;
