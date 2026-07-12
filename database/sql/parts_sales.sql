-- ============================================================================
--  Parts sales history — imported spare-part sales (the "Sales Log" spreadsheet).
--
--  This is the record-only history of parts sold, loaded from a sheet. It is the parts
--  analogue of how imported motorcycle sales live as figures on the unit: each row is a
--  historical sale line, NOT a live invoice, and it NEVER writes stock (current on-hand
--  is set separately from the inventory snapshot, so replaying these would double-count).
--
--  The Sales Log report unions these rows into the parts revenue stream alongside live
--  invoice_lines; the two sources are disjoint (live POS invoices vs imported history),
--  so nothing is counted twice.
--
--  Additive table only; no data changed. Idempotent. Reuses report.read to view (via the
--  existing Sales Log) and data.import to load, so no new permission is seeded.
-- ============================================================================

CREATE TABLE IF NOT EXISTS parts_sales (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id      UUID REFERENCES branches(id) ON DELETE SET NULL,
    -- Resolved from the sheet's item code; kept nullable so a sale of a code not in the
    -- catalog is still recorded (the code + description are retained regardless).
    product_id     UUID REFERENCES products(id) ON DELETE SET NULL,
    item_code      TEXT NOT NULL,
    description    TEXT,
    sale_date      DATE NOT NULL,
    qty            NUMERIC(18, 4) NOT NULL,
    unit_price_usd NUMERIC(18, 4),
    fx_rate        NUMERIC(18, 6),
    -- Ex-VAT line total in ZMW — the basis the Sales Log uses for parts revenue.
    revenue_zmw    NUMERIC(18, 4) NOT NULL,
    vat_zmw        NUMERIC(18, 4),
    customer_name  TEXT,
    remarks        TEXT,
    imported_historical BOOLEAN NOT NULL DEFAULT true,
    import_job_id  UUID REFERENCES import_jobs(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_parts_sales_tenant_date ON parts_sales (tenant_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_parts_sales_product ON parts_sales (product_id);
CREATE INDEX IF NOT EXISTS idx_parts_sales_import_job ON parts_sales (import_job_id);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants. Explicit statements (no format() / no percent / no colon —
-- this file is also run through SQLAlchemy op.execute(), which scans for bind markers).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    ALTER TABLE parts_sales ENABLE ROW LEVEL SECURITY;
    ALTER TABLE parts_sales FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'parts_sales' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON parts_sales
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON parts_sales TO app_user;
    END IF;
END
$$;

COMMENT ON TABLE parts_sales IS 'Imported historical spare-part sales (Sales Log). Record-only; never writes stock. Unioned into the Sales Log parts revenue alongside live invoice_lines.';
