-- ============================================================================
--  Order Request — completion (receipt confirmation) + cancellation support
--  (additive, idempotent)
--
--  Builds on order_requests.sql:
--    • adds the terminal 'completed' status (issued -> completed)
--    • adds receipt-confirmation columns on the header (who/when/remarks)
--    • adds per-line discrepancy capture (received / missing / damaged)
--    • adds the order_request.complete permission + role grants
--
--  'cancelled' was already part of the status set in order_requests.sql; this script
--  only needs to surface it via the new API/UI (no schema change for cancel).
--
--  Idempotent: safe as a fresh-init script and as an Alembic migration.
-- ============================================================================

-- 1) Allow the new terminal 'completed' status (recreate the inline status CHECK).
ALTER TABLE request_headers DROP CONSTRAINT IF EXISTS request_headers_status_check;
ALTER TABLE request_headers ADD CONSTRAINT request_headers_status_check
    CHECK (status IN
        ('pending','approved','partially_approved','rejected','issued','cancelled','completed'));

-- 2) Receipt confirmation on the header — set only on the issued -> completed transition.
ALTER TABLE request_headers ADD COLUMN IF NOT EXISTS completed_by       UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE request_headers ADD COLUMN IF NOT EXISTS completed_date     TIMESTAMPTZ;
ALTER TABLE request_headers ADD COLUMN IF NOT EXISTS completion_remarks TEXT;

-- 3) Per-line receipt reconciliation captured at completion time (all optional).
ALTER TABLE request_lines ADD COLUMN IF NOT EXISTS received_qty NUMERIC(18,4) CHECK (received_qty >= 0);
ALTER TABLE request_lines ADD COLUMN IF NOT EXISTS missing_qty  NUMERIC(18,4) CHECK (missing_qty  >= 0);
ALTER TABLE request_lines ADD COLUMN IF NOT EXISTS damaged_qty  NUMERIC(18,4) CHECK (damaged_qty  >= 0);

-- 4) Permission to confirm receipt + close a request, granted to the receiving roles.
INSERT INTO permissions (code, description) VALUES
    ('order_request.complete', 'Confirm receipt and close (complete) an issued order request')
ON CONFLICT (code) DO NOTHING;

-- Receiving users: admins, warehouse/branch managers, and the branch cashiers who take delivery.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'order_request.complete'
WHERE r.is_system AND r.name IN ('Admin','Warehouse Manager','Branch Manager','Cashier')
ON CONFLICT DO NOTHING;
