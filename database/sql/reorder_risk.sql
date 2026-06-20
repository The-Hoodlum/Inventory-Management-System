-- ============================================================================
--  Risk overlay on reorder recommendations  (additive, idempotent)
--
--  Persists the supply-risk context behind a recommendation so it is durable and
--  queryable: the risk score, the extra lead-time days risk added, the estimated
--  financial impact of the risk-driven uplift, and which signals contributed.
--
--  Idempotent: safe as a fresh-init script (docker-compose) and as Alembic
--  migration 0008 on an already-provisioned database.
-- ============================================================================

ALTER TABLE reorder_recommendations
    ADD COLUMN IF NOT EXISTS risk_score          NUMERIC(6,4)  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lead_time_extra_days NUMERIC(18,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS risk_cost_impact     NUMERIC(18,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS expedite             BOOLEAN       NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS risk_drivers         JSONB;

CREATE INDEX IF NOT EXISTS idx_reco_risk ON reorder_recommendations (tenant_id, risk_score DESC);

COMMENT ON COLUMN reorder_recommendations.risk_cost_impact IS
    'Estimated added inventory investment from the risk-driven uplift: (risk_units - base_units) x unit_cost.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON reorder_recommendations TO app_user;
    END IF;
END
$$;
