-- ============================================================================
--  Sales returns + credit notes  (additive, idempotent)  — Sales phase 2
--
--  A customer return brings goods BACK into a chosen branch + location (a stock
--  INFLOW through the inventory ledger), then a credit note — the financial
--  counterpart — is raised against the invoice. Historical invoices are NEVER
--  edited; a credit note offsets them (invoices.credit_total), so the customer's
--  net balance reflects the credit.
--
--    returns / return_lines        goods coming back (reason + restock location)
--    credit_notes / credit_note_lines  draft -> approved -> applied -> cancelled
--    invoices.credit_total         denormalised applied-credit total (immutable invoice)
--
--  Reuses next_sales_number() (doc types 'return' -> RET, 'credit_note' -> CN).
--  Generic + industry-agnostic. Idempotent.
-- ============================================================================

-- ---- Applied-credit total on the (immutable) invoice -----------------------
ALTER TABLE invoices
    ADD COLUMN IF NOT EXISTS credit_total NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (credit_total >= 0);

-- ---- Returns ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS returns (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    return_number TEXT NOT NULL,
    invoice_id    UUID REFERENCES invoices(id)            ON DELETE SET NULL,
    customer_id   UUID NOT NULL REFERENCES customers(id)  ON DELETE RESTRICT,
    branch_id     UUID REFERENCES branches(id)            ON DELETE RESTRICT,
    location_id   UUID REFERENCES warehouses(id)          ON DELETE RESTRICT,  -- where goods return
    reason        TEXT NOT NULL DEFAULT 'other' CHECK (reason IN
                    ('damaged','wrong_item','warranty','changed_mind','other')),
    status        TEXT NOT NULL DEFAULT 'received' CHECK (status IN
                    ('draft','received','credited','cancelled')),
    notes         TEXT,
    created_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    received_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, return_number)
);
CREATE INDEX IF NOT EXISTS idx_returns_invoice ON returns (invoice_id);
CREATE INDEX IF NOT EXISTS idx_returns_tenant_status ON returns (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS return_lines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    return_id       UUID NOT NULL REFERENCES returns(id)    ON DELETE CASCADE,
    invoice_line_id UUID REFERENCES invoice_lines(id)       ON DELETE SET NULL,
    product_id      UUID NOT NULL REFERENCES products(id)   ON DELETE RESTRICT,
    qty             NUMERIC(18,4) NOT NULL CHECK (qty > 0),
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_return_lines_return ON return_lines (return_id);

-- ---- Credit notes ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS credit_notes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES tenants(id)   ON DELETE CASCADE,
    credit_note_number TEXT NOT NULL,
    invoice_id         UUID REFERENCES invoices(id)           ON DELETE SET NULL,
    return_id          UUID REFERENCES returns(id)            ON DELETE SET NULL,
    customer_id        UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    branch_id          UUID REFERENCES branches(id)           ON DELETE RESTRICT,
    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                         ('draft','approved','applied','cancelled')),
    subtotal           NUMERIC(18,4) NOT NULL DEFAULT 0,
    discount_total     NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_total          NUMERIC(18,4) NOT NULL DEFAULT 0,
    grand_total        NUMERIC(18,4) NOT NULL DEFAULT 0,
    notes              TEXT,
    created_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    applied_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, credit_note_number)
);
CREATE INDEX IF NOT EXISTS idx_credit_notes_invoice ON credit_notes (invoice_id);
CREATE INDEX IF NOT EXISTS idx_credit_notes_tenant_status ON credit_notes (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS credit_note_lines (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)       ON DELETE CASCADE,
    credit_note_id UUID NOT NULL REFERENCES credit_notes(id)  ON DELETE CASCADE,
    product_id     UUID NOT NULL REFERENCES products(id)      ON DELETE RESTRICT,
    description    TEXT,
    qty            NUMERIC(18,4) NOT NULL CHECK (qty > 0),
    unit_price     NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    discount_pct   NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    tax_pct        NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (tax_pct >= 0),
    line_total     NUMERIC(18,4) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_credit_note_lines_cn ON credit_note_lines (credit_note_id);

-- ---- updated_at triggers ---------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['returns','credit_notes']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I;', t, t);
        EXECUTE format('CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at();', t, t);
    END LOOP;
END
$$;

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['returns','return_lines','credit_notes','credit_note_lines']
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
END
$$;

-- ---- Permission: process returns + credit notes ----------------------------
INSERT INTO permissions (code, description) VALUES
    ('sales.return', 'Process customer returns and credit notes')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'sales.return'
WHERE r.is_system AND r.name IN ('Admin','Branch Manager','Finance','Warehouse Manager')
ON CONFLICT DO NOTHING;
