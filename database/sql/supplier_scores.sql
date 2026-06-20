-- ============================================================================
--  Supplier Intelligence scorecards  (additive, idempotent)
--
--  A durable, queryable scorecard per supplier, recomputed from purchase-order
--  history and BLENDED with active intelligence signals (so a tariff or freight
--  shock on a supplier's country lowers its score — "future signals influence
--  supplier risk"). Rows are kept (not upserted) so a score trend can be drawn.
--
--    reliability           1 - blended risk
--    performance_risk      internal risk from delivery history (on-time/variance/fill)
--    intelligence_risk     risk from active supplier/country signals
--    risk_score            blended (probabilistic-OR of the two)
--    lead_time_accuracy    1 - lead-time coefficient of variation
--    delivery_performance  on-time delivery rate
--    fill_rate             received / ordered
--    purchase history      po_count, received_po_count, total_spend, last_order_at
--
--  Idempotent: safe as a fresh-init script and as Alembic migration 0010.
-- ============================================================================

CREATE TABLE IF NOT EXISTS supplier_scores (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    supplier_id          UUID NOT NULL REFERENCES suppliers(id)  ON DELETE CASCADE,
    supplier_name        TEXT NOT NULL,
    on_time_rate         NUMERIC(6,4),
    avg_lead_time_days   NUMERIC(18,4),
    lead_time_stdev_days NUMERIC(18,4),
    lead_time_accuracy   NUMERIC(6,4),
    fill_rate            NUMERIC(6,4),
    delivery_performance NUMERIC(6,4),
    reliability          NUMERIC(6,4) NOT NULL DEFAULT 1 CHECK (reliability >= 0 AND reliability <= 1),
    performance_risk     NUMERIC(6,4) NOT NULL DEFAULT 0 CHECK (performance_risk >= 0 AND performance_risk <= 1),
    intelligence_risk    NUMERIC(6,4) NOT NULL DEFAULT 0 CHECK (intelligence_risk >= 0 AND intelligence_risk <= 1),
    risk_score           NUMERIC(6,4) NOT NULL DEFAULT 0 CHECK (risk_score >= 0 AND risk_score <= 1),
    grade                TEXT NOT NULL CHECK (grade IN ('A','B','C','D','F')),
    po_count             INT NOT NULL DEFAULT 0,
    received_po_count    INT NOT NULL DEFAULT 0,
    total_spend          NUMERIC(18,4) NOT NULL DEFAULT 0,
    last_order_at        TIMESTAMPTZ,
    drivers              JSONB,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_supplier_scores_latest
    ON supplier_scores (supplier_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_supplier_scores_tenant_risk
    ON supplier_scores (tenant_id, risk_score DESC);

ALTER TABLE supplier_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_scores FORCE  ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'supplier_scores' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON supplier_scores
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON supplier_scores TO app_user;
    END IF;
END
$$;
