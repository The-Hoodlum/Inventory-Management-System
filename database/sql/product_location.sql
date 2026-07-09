-- ============================================================================
--  Product storage location (bin / shelf / aisle) so spare parts can be found
--  physically. Free text, per product. Additive + idempotent.
-- ============================================================================

ALTER TABLE products ADD COLUMN IF NOT EXISTS location TEXT;

COMMENT ON COLUMN products.location IS 'Physical storage location of the product (e.g. bin / shelf / aisle) — helps staff locate spare parts.';
