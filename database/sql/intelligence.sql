-- ============================================================================
--  Supply-chain intelligence data layer  (additive, idempotent)
--
--  Stores normalised intelligence OBSERVATIONS from every category (freight,
--  port, commodity, trade, supplier, geopolitical), whatever their origin
--  (computed internally, manually entered by an analyst, or ingested from an
--  external feed such as Freightos / Xeneta). Each observation carries:
--    * severity      its contribution to a 0..1 supply-risk score
--    * demand_factor a multiplicative effect on forecast demand (1.0 = none)
--    * confidence    how much to trust it (0..1)
--    * scope         what it applies to (global, a country, a supplier, ...)
--    * expires_at    when it should stop influencing decisions
--
--  These rows are read by the IntelligenceForecastSignal bridge and fed into the
--  forecast SignalPipeline, and aggregated by the intelligence dashboard.
--
--  Idempotent: safe as a fresh-init script (docker-compose) and as Alembic
--  migration 0007 on an already-provisioned database.
-- ============================================================================

CREATE TABLE IF NOT EXISTS intelligence_signals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    category      TEXT NOT NULL CHECK (category IN
                    ('freight','port','commodity','trade','supplier','geopolitical')),
    scope_type    TEXT NOT NULL CHECK (scope_type IN
                    ('global','country','supplier','commodity','route','port')),
    scope_key     TEXT,                              -- NULL for global; else country/supplier-id/commodity/...
    severity      NUMERIC(6,4) NOT NULL DEFAULT 0 CHECK (severity >= 0 AND severity <= 1),
    demand_factor NUMERIC(8,4) NOT NULL DEFAULT 1 CHECK (demand_factor > 0),
    confidence    NUMERIC(6,4) NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    headline      TEXT NOT NULL,                     -- human-readable reason
    value         NUMERIC(18,4),                     -- optional metric (e.g. index level, % change)
    unit          TEXT,
    trend         TEXT CHECK (trend IS NULL OR trend IN ('up','down','flat')),
    source        TEXT NOT NULL,                     -- supplier_risk | manual | freightos | xeneta | ...
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ,                       -- NULL = no expiry
    detail        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intel_tenant_cat ON intelligence_signals (tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_intel_scope      ON intelligence_signals (scope_type, scope_key);
CREATE INDEX IF NOT EXISTS idx_intel_expires    ON intelligence_signals (expires_at);

ALTER TABLE intelligence_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE intelligence_signals FORCE  ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'intelligence_signals'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON intelligence_signals
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON intelligence_signals TO app_user;
    END IF;
END
$$;
