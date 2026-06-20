-- ============================================================================
--  Demand forecasts  (additive, idempotent)
--
--  Stores each generated forecast so accuracy can be tracked over time against
--  realised demand in sales_daily. Records BOTH the base (pre-signal) daily
--  demand and the adjusted (post-signal) value plus a supply-risk score, so the
--  future intelligence layer can be added without a schema change.
--
--  Idempotent: safe as a fresh-init script (docker-compose) and as Alembic
--  migration 0006 on an already-provisioned database.
-- ============================================================================

CREATE TABLE IF NOT EXISTS demand_forecasts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    product_id            UUID NOT NULL REFERENCES products(id)   ON DELETE CASCADE,
    warehouse_id          UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    method                TEXT NOT NULL,                 -- provider key (moving_average, ...)
    window_days           INT  NOT NULL CHECK (window_days  >= 1),
    horizon_days          INT  NOT NULL CHECK (horizon_days >= 1),
    forecast_date         DATE NOT NULL,                 -- first day the forecast applies to
    daily_demand          NUMERIC(18,4) NOT NULL,        -- base, pre-signal
    adjusted_daily_demand NUMERIC(18,4) NOT NULL,        -- post-signal (== base until signals exist)
    std_dev_daily         NUMERIC(18,4) NOT NULL DEFAULT 0,
    confidence            NUMERIC(6,4)  NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    risk_score            NUMERIC(6,4)  NOT NULL DEFAULT 0 CHECK (risk_score >= 0 AND risk_score <= 1),
    observations          INT NOT NULL DEFAULT 0,
    days_with_demand      INT NOT NULL DEFAULT 0,
    total_demand          NUMERIC(18,4) NOT NULL DEFAULT 0,
    params                JSONB,                         -- provider tunables (alpha, ma_window, ...)
    generated_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    generated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecasts_pwh
    ON demand_forecasts (product_id, warehouse_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_forecasts_tenant
    ON demand_forecasts (tenant_id, generated_at DESC);

-- Row-Level Security (tenant isolation), matching the rest of the schema.
ALTER TABLE demand_forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE demand_forecasts FORCE  ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'demand_forecasts'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON demand_forecasts
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON demand_forecasts TO app_user;
    END IF;
END
$$;
