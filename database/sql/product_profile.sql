-- ============================================================================
--  Product Intelligence Profile  (additive, idempotent)
--
--  Extends products with the structured attributes that the forecast, risk,
--  procurement, intelligence, and (future) AI engines consume:
--    commodity_tags       what the product is made of (binds commodity signals)
--    country_of_origin    where it ships from (binds country/freight/port/trade signals)
--    transport_mode       sea | air | road | rail | multimodal
--    criticality          how badly a stockout hurts (low|medium|high|critical)
--    supplier_dependency  sourcing concentration (single|dual|multi)
--    demand_type          demand character (smooth|erratic|intermittent|lumpy|seasonal)
--    substitutability     how replaceable it is (none|low|medium|high)
--
--  Carton dimensions for container optimization already exist as
--  volume_per_carton (m³) and weight_per_carton (kg); the ProductProfile value
--  object exposes them as carton_volume_m3 / carton_weight_kg — no duplicate
--  columns are added.
--
--  Idempotent: safe as a fresh-init script (docker-compose) and as Alembic
--  migration 0009 on an already-provisioned database. New columns are nullable
--  or defaulted, so existing rows and queries are unaffected.
-- ============================================================================

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS commodity_tags      JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS country_of_origin   TEXT,
    ADD COLUMN IF NOT EXISTS transport_mode      TEXT,
    ADD COLUMN IF NOT EXISTS criticality         TEXT NOT NULL DEFAULT 'medium',
    ADD COLUMN IF NOT EXISTS supplier_dependency TEXT,
    ADD COLUMN IF NOT EXISTS demand_type         TEXT,
    ADD COLUMN IF NOT EXISTS substitutability    TEXT;

-- Value-domain CHECK constraints, added once (guarded so re-runs are no-ops).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_transport_mode') THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_transport_mode
            CHECK (transport_mode IS NULL OR transport_mode IN ('sea','air','road','rail','multimodal'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_criticality') THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_criticality
            CHECK (criticality IN ('low','medium','high','critical'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_supplier_dependency') THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_supplier_dependency
            CHECK (supplier_dependency IS NULL OR supplier_dependency IN ('single','dual','multi'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_demand_type') THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_demand_type
            CHECK (demand_type IS NULL OR demand_type IN ('smooth','erratic','intermittent','lumpy','seasonal'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_substitutability') THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_substitutability
            CHECK (substitutability IS NULL OR substitutability IN ('none','low','medium','high'));
    END IF;
END
$$;

-- GIN index so commodity-tag membership lookups (intelligence matching) are fast.
CREATE INDEX IF NOT EXISTS idx_products_commodity_tags ON products USING gin (commodity_tags);
CREATE INDEX IF NOT EXISTS idx_products_origin ON products (country_of_origin) WHERE country_of_origin IS NOT NULL;

COMMENT ON COLUMN products.commodity_tags IS 'JSON array of commodity keys (e.g. ["steel","copper"]); binds commodity intelligence signals to the product.';
COMMENT ON COLUMN products.country_of_origin IS 'ISO-2 country the product ships from; binds country/freight/port/trade signals.';
COMMENT ON COLUMN products.criticality IS 'Stockout impact: low|medium|high|critical. Amplifies supply-risk in the reorder engine.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON products TO app_user;
    END IF;
END
$$;
