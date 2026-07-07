-- ============================================================================
--  Assembly targets — per model/colour tuning for the Assembly Planner.
--
--  The planner recommends deterministically from CURRENT stock (assembled vs
--  unassembled counts); this table lets a tenant tune, per model (optionally per
--  colour), how many assembled units to keep (target_assembled) and how thin is "thin"
--  (threshold). When no row matches, the planner falls back to sensible module defaults.
--  It stores NO demand/velocity data — the planner never predicts demand.
--
--  Additive table only; no data changed. Idempotent. Reuses the existing motorcycle
--  permissions (motorcycle.read to view the plan, motorcycle.config to tune targets), so
--  no new permission is seeded here.
-- ============================================================================

CREATE TABLE IF NOT EXISTS assembly_targets (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    model_id         UUID NOT NULL REFERENCES motorcycle_models(id)  ON DELETE CASCADE,
    -- NULL colour = a model-wide default across all colours.
    colour_id        UUID REFERENCES motorcycle_colours(id) ON DELETE CASCADE,
    target_assembled INTEGER NOT NULL CHECK (target_assembled >= 1),
    threshold        INTEGER NOT NULL CHECK (threshold >= 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One override per (tenant, model, colour); NULL colour handled with a partial index so a
-- model-wide default is also unique (NULLs are otherwise distinct in a plain UNIQUE).
CREATE UNIQUE INDEX IF NOT EXISTS uq_assembly_targets_model_colour
    ON assembly_targets (tenant_id, model_id, colour_id) WHERE colour_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_assembly_targets_model_default
    ON assembly_targets (tenant_id, model_id) WHERE colour_id IS NULL;

DROP TRIGGER IF EXISTS trg_assembly_targets_updated_at ON assembly_targets;
CREATE TRIGGER trg_assembly_targets_updated_at
    BEFORE UPDATE ON assembly_targets FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS + app_user grants
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    ALTER TABLE assembly_targets ENABLE ROW LEVEL SECURITY;
    ALTER TABLE assembly_targets FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'assembly_targets' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON assembly_targets
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON assembly_targets TO app_user;
    END IF;
END
$$;

COMMENT ON TABLE assembly_targets IS 'Per model/colour tuning for the Assembly Planner: how many assembled units to keep (target_assembled) and the thinness threshold. Falls back to module defaults when absent. Holds no demand data.';
