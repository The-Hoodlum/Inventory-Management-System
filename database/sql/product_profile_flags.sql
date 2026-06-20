-- ============================================================================
--  Product Intelligence Profile — strategic flags  (additive, idempotent)
--
--  Two boolean profile attributes the forecast/risk/AI engines and the import
--  framework consume, alongside the existing criticality / substitutability /
--  supplier_dependency:
--    strategic_item                 a strategically important SKU (raises supply risk)
--    alternate_supplier_available   a qualified second source exists (lowers risk)
--
--  (unit_of_measure + currency were added in migration 0011; criticality already
--  allows 'critical'. This migration only adds the two flags.)
--
--  Idempotent: safe as a fresh-init script and as Alembic migration 0013.
-- ============================================================================
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS strategic_item                BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS alternate_supplier_available  BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN products.strategic_item IS 'Strategically important SKU; amplifies supply-risk in the reorder/AI engines.';
COMMENT ON COLUMN products.alternate_supplier_available IS 'A qualified second source exists; mitigates single-source supply risk.';
