-- ============================================================================
--  Customers + Sales/POS RBAC foundation  (additive, idempotent)
--
--  The customer master for the Sales & Distribution module, plus the shared
--  permission + role foundation that every sales document (quotation, sales
--  order, delivery note, invoice, payment, receipt, POS) is gated on.
--
--    customers           one row per customer (tenant-scoped; code unique per tenant)
--    customer_addresses  billing/shipping/other addresses per customer
--    customer_counters   per-tenant sequence backing next_customer_number()
--
--  Generic + industry-agnostic. Idempotent: safe as a fresh-init script and as an
--  Alembic migration.
-- ============================================================================

-- ---- Per-tenant customer code sequence (CUST-00001) ------------------------
CREATE TABLE IF NOT EXISTS customer_counters (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    last_seq  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id)
);

CREATE OR REPLACE FUNCTION next_customer_number(p_tenant UUID)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE v_seq INT;
BEGIN
    INSERT INTO customer_counters (tenant_id, last_seq)
    VALUES (p_tenant, 1)
    ON CONFLICT (tenant_id)
    DO UPDATE SET last_seq = customer_counters.last_seq + 1
    RETURNING last_seq INTO v_seq;
    RETURN 'CUST-' || lpad(v_seq::text, 5, '0');
END;
$$;

CREATE TABLE IF NOT EXISTS customers (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    name           TEXT NOT NULL,
    contact_name   TEXT,
    phone          TEXT,
    email          TEXT,
    tax_number     TEXT,
    currency       TEXT,                                   -- null => tenant default
    payment_terms  TEXT,                                   -- e.g. 'net_30', 'cod'
    credit_limit   NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
    notes          TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant      ON customers (tenant_id);
CREATE INDEX IF NOT EXISTS idx_customers_tenant_name ON customers (tenant_id, name);

DROP TRIGGER IF EXISTS trg_customers_updated_at ON customers;
CREATE TRIGGER trg_customers_updated_at
    BEFORE UPDATE ON customers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS customer_addresses (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    customer_id  UUID NOT NULL REFERENCES customers(id)  ON DELETE CASCADE,
    address_type TEXT NOT NULL DEFAULT 'shipping' CHECK (address_type IN ('billing','shipping','other')),
    line1        TEXT,
    line2        TEXT,
    city         TEXT,
    region       TEXT,
    country      TEXT,
    is_default   BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_addresses_customer ON customer_addresses (customer_id);

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['customers','customer_addresses']
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
        GRANT SELECT, INSERT, UPDATE ON customer_counters TO app_user;
    END IF;
END
$$;

-- ---- Sales/POS roles + permissions (shared by every sales document) --------
INSERT INTO roles (tenant_id, name, description, is_system) VALUES
    (NULL, 'Salesperson', 'Creates quotations and sales orders; manages customers', TRUE),
    (NULL, 'Finance',     'Invoices, payments, receipts and credit control',         TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO permissions (code, description) VALUES
    ('customer.read',   'View customers'),
    ('customer.manage', 'Create / update customers and addresses'),
    ('sales.read',      'View sales documents (quotations, orders, deliveries, invoices)'),
    ('sales.quote',     'Create / send / convert quotations'),
    ('sales.order',     'Create / confirm sales orders (reserves stock)'),
    ('sales.deliver',   'Issue delivery notes (deducts inventory)'),
    ('sales.invoice',   'Create / send invoices'),
    ('sales.payment',   'Record payments and issue receipts'),
    ('sales.manage',    'Approve discounts, cancel documents, override sales workflow'),
    ('pos.use',         'Operate the point-of-sale fast-sale checkout')
ON CONFLICT (code) DO NOTHING;

-- Admin: everything.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('customer.read','customer.manage','sales.read','sales.quote','sales.order',
     'sales.deliver','sales.invoice','sales.payment','sales.manage','pos.use')
WHERE r.is_system AND r.name = 'Admin'
ON CONFLICT DO NOTHING;

-- Branch Manager: full sales operations within the branch.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('customer.read','customer.manage','sales.read','sales.quote','sales.order',
     'sales.deliver','sales.invoice','sales.payment','sales.manage','pos.use')
WHERE r.is_system AND r.name = 'Branch Manager'
ON CONFLICT DO NOTHING;

-- Salesperson: customers, quotations, sales orders, and invoicing (quote -> invoice).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('customer.read','customer.manage','sales.read','sales.quote','sales.order','sales.invoice')
WHERE r.is_system AND r.name = 'Salesperson'
ON CONFLICT DO NOTHING;

-- Cashier: POS, payments, receipts, read, plus create quotations + invoices for a customer
-- (bikes by chassis / parts by SKU). The one-step quote -> invoice orchestrates the order
-- internally, so the cashier needs sales.quote + sales.invoice (not sales.order).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('customer.read','sales.read','pos.use','sales.payment','sales.quote','sales.invoice')
WHERE r.is_system AND r.name = 'Cashier'
ON CONFLICT DO NOTHING;

-- Warehouse Manager: deliveries.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('sales.read','sales.deliver')
WHERE r.is_system AND r.name = 'Warehouse Manager'
ON CONFLICT DO NOTHING;

-- Finance: invoices, payments, receipts.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('customer.read','sales.read','sales.invoice','sales.payment','sales.manage')
WHERE r.is_system AND r.name = 'Finance'
ON CONFLICT DO NOTHING;

COMMENT ON TABLE customers          IS 'Sales customer master (tenant-scoped). Outstanding balance is derived from unpaid invoices.';
COMMENT ON TABLE customer_addresses IS 'Billing/shipping/other addresses per customer.';
