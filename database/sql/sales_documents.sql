-- ============================================================================
--  Sales documents  (additive, idempotent)  — the shared Sales & Distribution spine
--
--  One traceable chain, every document linked to the previous:
--     quotation -> sales_order -> delivery_note -> invoice -> payment -> receipt
--
--  POS is the same chain executed in one fast transaction. Stock is RESERVED when a
--  sales order is confirmed and DEDUCTED only at delivery (or immediately at POS) —
--  always via the shared inventory engine, writing an auditable stock_movements row.
--  Money documents (invoice/payment/receipt) never touch inventory.
--
--    quotations / quotation_lines
--    sales_orders / sales_order_lines        (reserved_qty / delivered_qty per line)
--    delivery_notes / delivery_note_lines
--    invoices / invoice_lines
--    payments / payment_allocations          (multi-method + split; applied to invoices)
--    receipts
--    sales_counters  + next_sales_number()   (per-tenant/-year document numbering)
--
--  branch_id -> branches(id); location_id -> warehouses(id) (the selling/source location).
--  Generic + industry-agnostic. Idempotent.
-- ============================================================================

-- ---- One generic per-tenant/-year document counter -------------------------
CREATE TABLE IF NOT EXISTS sales_counters (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    doc_type  TEXT NOT NULL,
    year      INT  NOT NULL,
    last_seq  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, doc_type, year)
);

CREATE OR REPLACE FUNCTION next_sales_number(p_tenant UUID, p_doc_type TEXT, p_prefix TEXT)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE v_year INT := EXTRACT(YEAR FROM now())::int; v_seq INT;
BEGIN
    INSERT INTO sales_counters (tenant_id, doc_type, year, last_seq)
    VALUES (p_tenant, p_doc_type, v_year, 1)
    ON CONFLICT (tenant_id, doc_type, year)
    DO UPDATE SET last_seq = sales_counters.last_seq + 1
    RETURNING last_seq INTO v_seq;
    RETURN p_prefix || '-' || v_year::text || '-' || lpad(v_seq::text, 5, '0');
END;
$$;

-- ---- Quotations ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quotations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)   ON DELETE CASCADE,
    quote_number   TEXT NOT NULL,
    customer_id    UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    branch_id      UUID REFERENCES branches(id)           ON DELETE RESTRICT,
    salesperson_id UUID REFERENCES users(id)              ON DELETE SET NULL,
    currency       TEXT,
    valid_until    DATE,
    status         TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                     ('draft','sent','accepted','rejected','expired','cancelled')),
    notes          TEXT,
    subtotal       NUMERIC(18,4) NOT NULL DEFAULT 0,
    discount_total NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_total      NUMERIC(18,4) NOT NULL DEFAULT 0,
    grand_total    NUMERIC(18,4) NOT NULL DEFAULT 0,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, quote_number)
);
CREATE INDEX IF NOT EXISTS idx_quotations_tenant_status ON quotations (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotations_customer ON quotations (customer_id);

CREATE TABLE IF NOT EXISTS quotation_lines (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id)     ON DELETE CASCADE,
    quotation_id  UUID NOT NULL REFERENCES quotations(id)  ON DELETE CASCADE,
    product_id    UUID NOT NULL REFERENCES products(id)    ON DELETE RESTRICT,
    description   TEXT,
    qty           NUMERIC(18,4) NOT NULL CHECK (qty > 0),
    unit_price    NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    discount_pct  NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    tax_pct       NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (tax_pct >= 0),
    line_total    NUMERIC(18,4) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_quotation_lines_quote ON quotation_lines (quotation_id);

-- ---- Sales orders ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS sales_orders (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    so_number      TEXT NOT NULL,
    customer_id    UUID NOT NULL REFERENCES customers(id)  ON DELETE RESTRICT,
    branch_id      UUID REFERENCES branches(id)            ON DELETE RESTRICT,
    location_id    UUID REFERENCES warehouses(id)          ON DELETE RESTRICT,   -- selling/source location
    salesperson_id UUID REFERENCES users(id)               ON DELETE SET NULL,
    quotation_id   UUID REFERENCES quotations(id)          ON DELETE SET NULL,   -- source link
    currency       TEXT,
    payment_terms  TEXT,
    delivery_terms TEXT,
    status         TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                     ('draft','confirmed','reserved','picking','partially_delivered','delivered','cancelled')),
    notes          TEXT,
    subtotal       NUMERIC(18,4) NOT NULL DEFAULT 0,
    discount_total NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_total      NUMERIC(18,4) NOT NULL DEFAULT 0,
    grand_total    NUMERIC(18,4) NOT NULL DEFAULT 0,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, so_number)
);
CREATE INDEX IF NOT EXISTS idx_sales_orders_tenant_status ON sales_orders (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sales_orders_customer ON sales_orders (customer_id);

CREATE TABLE IF NOT EXISTS sales_order_lines (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)      ON DELETE CASCADE,
    sales_order_id UUID NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    product_id     UUID NOT NULL REFERENCES products(id)     ON DELETE RESTRICT,
    description    TEXT,
    qty            NUMERIC(18,4) NOT NULL CHECK (qty > 0),
    unit_price     NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    discount_pct   NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    tax_pct        NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (tax_pct >= 0),
    line_total     NUMERIC(18,4) NOT NULL DEFAULT 0,
    reserved_qty   NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
    delivered_qty  NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (delivered_qty >= 0)
);
CREATE INDEX IF NOT EXISTS idx_sales_order_lines_so ON sales_order_lines (sales_order_id);

-- ---- Delivery notes --------------------------------------------------------
CREATE TABLE IF NOT EXISTS delivery_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id)      ON DELETE CASCADE,
    delivery_number TEXT NOT NULL,
    sales_order_id  UUID REFERENCES sales_orders(id)          ON DELETE SET NULL,
    customer_id     UUID NOT NULL REFERENCES customers(id)    ON DELETE RESTRICT,
    branch_id       UUID REFERENCES branches(id)              ON DELETE RESTRICT,
    location_id     UUID REFERENCES warehouses(id)            ON DELETE RESTRICT,  -- source location deducted
    delivery_address TEXT,
    driver          TEXT,
    vehicle         TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                      ('pending','delivered','partially_delivered','returned')),
    received_by     TEXT,
    signature       TEXT,
    notes           TEXT,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, delivery_number)
);
CREATE INDEX IF NOT EXISTS idx_delivery_notes_so ON delivery_notes (sales_order_id);
CREATE INDEX IF NOT EXISTS idx_delivery_notes_tenant_status ON delivery_notes (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS delivery_note_lines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id)         ON DELETE CASCADE,
    delivery_note_id    UUID NOT NULL REFERENCES delivery_notes(id)  ON DELETE CASCADE,
    sales_order_line_id UUID REFERENCES sales_order_lines(id)        ON DELETE SET NULL,
    product_id          UUID NOT NULL REFERENCES products(id)        ON DELETE RESTRICT,
    qty                 NUMERIC(18,4) NOT NULL CHECK (qty > 0)
);
CREATE INDEX IF NOT EXISTS idx_delivery_note_lines_dn ON delivery_note_lines (delivery_note_id);

-- ---- Invoices --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id)     ON DELETE CASCADE,
    invoice_number   TEXT NOT NULL,
    sales_order_id   UUID REFERENCES sales_orders(id)         ON DELETE SET NULL,
    delivery_note_id UUID REFERENCES delivery_notes(id)       ON DELETE SET NULL,
    customer_id      UUID NOT NULL REFERENCES customers(id)   ON DELETE RESTRICT,
    branch_id        UUID REFERENCES branches(id)             ON DELETE RESTRICT,
    currency         TEXT,
    payment_terms    TEXT,
    invoice_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date         DATE,
    status           TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                       ('draft','sent','partially_paid','paid','overdue','cancelled')),
    subtotal         NUMERIC(18,4) NOT NULL DEFAULT 0,
    discount_total   NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_total        NUMERIC(18,4) NOT NULL DEFAULT 0,
    grand_total      NUMERIC(18,4) NOT NULL DEFAULT 0,
    amount_paid      NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant_status ON invoices (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices (customer_id);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id)   ON DELETE CASCADE,
    invoice_id   UUID NOT NULL REFERENCES invoices(id)  ON DELETE CASCADE,
    product_id   UUID NOT NULL REFERENCES products(id)  ON DELETE RESTRICT,
    description  TEXT,
    qty          NUMERIC(18,4) NOT NULL CHECK (qty > 0),
    unit_price   NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    discount_pct NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    tax_pct      NUMERIC(9,4)  NOT NULL DEFAULT 0 CHECK (tax_pct >= 0),
    line_total   NUMERIC(18,4) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines (invoice_id);

-- ---- Payments + allocations + receipts -------------------------------------
CREATE TABLE IF NOT EXISTS receipts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    receipt_number TEXT NOT NULL,
    invoice_id     UUID REFERENCES invoices(id)            ON DELETE SET NULL,
    customer_id    UUID REFERENCES customers(id)           ON DELETE RESTRICT,
    branch_id      UUID REFERENCES branches(id)            ON DELETE RESTRICT,
    cashier_id     UUID REFERENCES users(id)               ON DELETE SET NULL,
    amount_paid    NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
    balance        NUMERIC(18,4) NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, receipt_number)
);
CREATE INDEX IF NOT EXISTS idx_receipts_invoice ON receipts (invoice_id);

CREATE TABLE IF NOT EXISTS payments (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
    payment_number TEXT NOT NULL,
    customer_id    UUID REFERENCES customers(id)         ON DELETE RESTRICT,
    branch_id      UUID REFERENCES branches(id)          ON DELETE RESTRICT,
    receipt_id     UUID REFERENCES receipts(id)          ON DELETE SET NULL,   -- groups split payments
    method         TEXT NOT NULL CHECK (method IN
                     ('cash','card','mobile_money','bank_transfer','cheque','store_credit')),
    amount         NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    reference      TEXT,
    received_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, payment_number)
);
CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments (customer_id);
CREATE INDEX IF NOT EXISTS idx_payments_receipt ON payments (receipt_id);

CREATE TABLE IF NOT EXISTS payment_allocations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
    payment_id  UUID NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    invoice_id  UUID NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
    amount      NUMERIC(18,4) NOT NULL CHECK (amount > 0)
);
CREATE INDEX IF NOT EXISTS idx_payment_allocations_payment ON payment_allocations (payment_id);
CREATE INDEX IF NOT EXISTS idx_payment_allocations_invoice ON payment_allocations (invoice_id);

-- ---- updated_at triggers ---------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['quotations','sales_orders','delivery_notes','invoices']
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
    FOREACH t IN ARRAY ARRAY[
        'quotations','quotation_lines','sales_orders','sales_order_lines',
        'delivery_notes','delivery_note_lines','invoices','invoice_lines',
        'payments','payment_allocations','receipts'
    ]
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
        GRANT SELECT, INSERT, UPDATE ON sales_counters TO app_user;
    END IF;
END
$$;
