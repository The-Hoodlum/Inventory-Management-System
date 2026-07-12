-- ============================================================================
--  VAT — a configurable tenant rate (default 16 percent) applied per line by the line's
--  TREATMENT: spare parts are VAT-EXCLUSIVE (net price, add 16 percent on top); motorcycles are
--  VAT-INCLUSIVE (price already contains VAT, extract it). net / vat / gross are FROZEN
--  on every document line + total (like the fx_rate), so a historical document keeps the
--  VAT that was applied and never recomputes it from today's rate.
--
--  Additive + idempotent; no stock touched. tenants.vat_rate already exists (was 0) — this
--  gives it the 16 percent default and backfills existing tenants.
-- ============================================================================

-- Tenant VAT rate (fraction: 0.16 == 16 percent). Configurable + audited like the fx rate.
ALTER TABLE tenants ALTER COLUMN vat_rate SET DEFAULT 0.16;
UPDATE tenants SET vat_rate = 0.16 WHERE vat_rate = 0;
COMMENT ON COLUMN tenants.vat_rate IS 'Current VAT rate as a fraction (0.16 = 16 percent). Editable + audited; snapshotted onto each sales document, never retroactive.';

-- VAT treatment is a property of the product (parts default EXCLUSIVE). Motorcycles are
-- sold INCLUSIVE via the bike-sale path (they are not products).
ALTER TABLE products ADD COLUMN IF NOT EXISTS vat_treatment TEXT NOT NULL DEFAULT 'exclusive';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_vat_treatment_ck') THEN
        ALTER TABLE products ADD CONSTRAINT products_vat_treatment_ck
            CHECK (vat_treatment IN ('inclusive', 'exclusive'));
    END IF;
END
$$;
COMMENT ON COLUMN products.vat_treatment IS 'How VAT applies to this product: exclusive (add on top) or inclusive (price already contains VAT).';

-- Document totals: freeze net + the rate applied (tax_total = VAT, grand_total = gross).
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['quotations', 'sales_orders', 'invoices', 'credit_notes']
    LOOP
        EXECUTE 'ALTER TABLE ' || t || ' ADD COLUMN IF NOT EXISTS net_total NUMERIC(18,4) NOT NULL DEFAULT 0';
        EXECUTE 'ALTER TABLE ' || t || ' ADD COLUMN IF NOT EXISTS vat_rate  NUMERIC(9,6)  NOT NULL DEFAULT 0';
    END LOOP;
END
$$;

-- Document lines: freeze net + VAT + the treatment/rate applied (line_total = gross).
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['quotation_lines', 'sales_order_lines', 'invoice_lines', 'credit_note_lines']
    LOOP
        EXECUTE 'ALTER TABLE ' || t || ' ADD COLUMN IF NOT EXISTS net_amount    NUMERIC(18,4) NOT NULL DEFAULT 0';
        EXECUTE 'ALTER TABLE ' || t || ' ADD COLUMN IF NOT EXISTS vat_amount    NUMERIC(18,4) NOT NULL DEFAULT 0';
        EXECUTE 'ALTER TABLE ' || t || ' ADD COLUMN IF NOT EXISTS vat_treatment TEXT NOT NULL DEFAULT ''exclusive''';
        EXECUTE 'ALTER TABLE ' || t || ' ADD COLUMN IF NOT EXISTS vat_rate      NUMERIC(9,6)  NOT NULL DEFAULT 0';
    END LOOP;
END
$$;
