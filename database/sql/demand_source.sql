-- ============================================================================
--  Demand source tagging on sales_daily  (additive, idempotent)
--
--  Adds a `source` column so the demand table can be fed by multiple channels
--  without collisions and remain the single source of truth for forecasting:
--      'issue'   derived from outbound stock movements (the automatic pipeline)
--      'import'  CSV / spreadsheet uploads          (future)
--      'pos'     point-of-sale integrations          (future)
--      'manual'  hand-entered / seeded historical sales
--
--  The uniqueness key becomes (product, warehouse, date, source) so each source
--  keeps its own daily figure; demand reads SUM across sources per day. Existing
--  rows (e.g. demo seed) are tagged 'manual'.
--
--  Idempotent: safe to run as a fresh-init script (docker-compose) and as Alembic
--  migration 0005 on an already-provisioned database.
-- ============================================================================

ALTER TABLE sales_daily
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual';

-- Replace the original 3-column unique with a 4-column one that includes source.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sales_daily_product_id_warehouse_id_sale_date_key'
    ) THEN
        ALTER TABLE sales_daily
            DROP CONSTRAINT sales_daily_product_id_warehouse_id_sale_date_key;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_sales_daily_pwds'
    ) THEN
        ALTER TABLE sales_daily
            ADD CONSTRAINT uq_sales_daily_pwds
            UNIQUE (product_id, warehouse_id, sale_date, source);
    END IF;
END
$$;

COMMENT ON COLUMN sales_daily.source IS
    'Demand channel: issue|import|pos|manual. Demand reads SUM(qty_sold) across sources per (product, warehouse, day).';

-- Grant to the application role when it exists (no-op otherwise; the column is
-- covered by the existing table grant, but kept explicit for parity).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON sales_daily TO app_user;
    END IF;
END
$$;
