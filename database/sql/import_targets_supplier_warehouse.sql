-- ============================================================================
--  Supplier & Warehouse spreadsheet-import support (additive, idempotent)
--
--  The generic import framework gains two new targets (suppliers, warehouses).
--  This adds the columns those targets populate that weren't on the original
--  models:
--      suppliers.code, suppliers.address
--      warehouses.branch, warehouses.warehouse_type  (main/depot/store/counter)
--
--  All columns are nullable / additive; existing rows and queries are unaffected,
--  and table-level grants/RLS already cover the new columns.
-- ============================================================================

ALTER TABLE suppliers  ADD COLUMN IF NOT EXISTS code    TEXT;
ALTER TABLE suppliers  ADD COLUMN IF NOT EXISTS address TEXT;

ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS branch         TEXT;
ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS warehouse_type TEXT
    CHECK (warehouse_type IS NULL OR warehouse_type IN ('main', 'depot', 'store', 'counter'));
