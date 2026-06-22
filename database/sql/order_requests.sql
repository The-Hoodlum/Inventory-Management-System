-- ============================================================================
--  Order Request (branch requisition) system  (additive, idempotent)
--
--  A branch user / cashier raises a request for stock held at the depot; an admin
--  approves (fully or partially) or rejects it, then ISSUES the stock — and only at
--  issue time is inventory deducted (one 'issue' stock movement per line). Full audit
--  trail in request_audit. Tenant-scoped by RLS; branches are warehouses.
--
--    request_headers  one row per requisition (status workflow + who/when)
--    request_lines    requested / approved / issued quantity per product
--    request_audit    every status transition (who, old -> new, when)
--    request_counters per-tenant/-year sequence backing next_request_number()
--
--  Idempotent: safe as a fresh-init script and as an Alembic migration.
-- ============================================================================

-- Per-tenant, per-year monotonic counter (mirrors po_counters / next_po_number).
CREATE TABLE IF NOT EXISTS request_counters (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    year      INT  NOT NULL,
    last_seq  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, year)
);

CREATE OR REPLACE FUNCTION next_request_number(p_tenant UUID)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    v_year INT := EXTRACT(YEAR FROM now())::int;
    v_seq  INT;
BEGIN
    INSERT INTO request_counters (tenant_id, year, last_seq)
    VALUES (p_tenant, v_year, 1)
    ON CONFLICT (tenant_id, year)
    DO UPDATE SET last_seq = request_counters.last_seq + 1
    RETURNING last_seq INTO v_seq;
    RETURN 'REQ-' || v_year::text || '-' || lpad(v_seq::text, 5, '0');
END;
$$;

CREATE TABLE IF NOT EXISTS request_headers (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    request_number TEXT NOT NULL,
    branch_id      UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    requested_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    purpose        TEXT NOT NULL CHECK (purpose IN
                     ('for_sale','shelf_replenishment','workshop_use','office_use','other')),
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                     ('pending','approved','partially_approved','rejected','issued','cancelled')),
    requested_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_date  TIMESTAMPTZ,
    issued_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    issued_date    TIMESTAMPTZ,
    comments       TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, request_number)
);
CREATE INDEX IF NOT EXISTS idx_req_tenant_status_time ON request_headers (tenant_id, status, requested_date DESC);
CREATE INDEX IF NOT EXISTS idx_req_branch ON request_headers (branch_id);
CREATE INDEX IF NOT EXISTS idx_req_requested_by ON request_headers (requested_by);

CREATE TABLE IF NOT EXISTS request_lines (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    request_id    UUID NOT NULL REFERENCES request_headers(id) ON DELETE CASCADE,
    product_id    UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    requested_qty NUMERIC(18,4) NOT NULL CHECK (requested_qty > 0),
    approved_qty  NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (approved_qty >= 0),
    issued_qty    NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (issued_qty  >= 0),
    remarks       TEXT
);
CREATE INDEX IF NOT EXISTS idx_req_lines_request ON request_lines (request_id);
CREATE INDEX IF NOT EXISTS idx_req_lines_product ON request_lines (product_id);

CREATE TABLE IF NOT EXISTS request_audit (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    request_id UUID NOT NULL REFERENCES request_headers(id) ON DELETE CASCADE,
    user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_req_audit_request ON request_audit (request_id, created_at);

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['request_headers','request_lines','request_audit']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY;', t);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING      (tenant_id = NULLIF(current_setting(''app.current_tenant'', true), '''')::uuid) '
                'WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant'', true), '''')::uuid);',
                t);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_user;', t);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE ON request_counters TO app_user;
    END IF;
END
$$;

-- ---- Permissions + role grants --------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('order_request.create',  'Create branch order requests (requisitions)'),
    ('order_request.read',    'View order requests'),
    ('order_request.approve', 'Approve / partially approve / reject order requests'),
    ('order_request.issue',   'Issue stock for an approved request (deducts inventory)')
ON CONFLICT (code) DO NOTHING;

-- create: branch staff + branch/operations managers + admin
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'order_request.create'
WHERE r.is_system AND r.name IN ('Admin','Warehouse Manager','Branch Manager','Cashier')
ON CONFLICT DO NOTHING;

-- read: everyone who can see inventory
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'order_request.read'
WHERE r.is_system AND r.name IN
    ('Admin','Warehouse Manager','Inventory Manager','Procurement Manager','Branch Manager','Cashier','Viewer')
ON CONFLICT DO NOTHING;

-- approve + issue: admins / branch+warehouse managers
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN ('order_request.approve','order_request.issue')
WHERE r.is_system AND r.name IN ('Admin','Warehouse Manager','Branch Manager')
ON CONFLICT DO NOTHING;
