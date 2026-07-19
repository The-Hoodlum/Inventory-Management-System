-- ============================================================================
--  Motorcycle reorder points — "are we running out of this model/colour?"
--
--  The reorder engine covers PARTS only: it works off products with a reorder_point and
--  inventory rows. Motorcycles are SERIALIZED units with a lifecycle status, so they have
--  no inventory row and no reorder point — nothing told you a colour was running out.
--
--  This table adds that: a sellable-stock threshold per MODEL, optionally per COLOUR.
--    * a row with a colour  -> the threshold for exactly that model+colour
--    * a row with NULL colour -> the model-wide default for every other colour
--    * no row at all        -> that model is not monitored (silent, never guessed)
--
--  Deliberately SEPARATE from assembly_targets: that tunes "how many should be assembled
--  and ready" (a workshop question). This answers "do we still have any to sell" (a
--  purchasing question). Sharing one number would make tuning one silently change the other.
--
--  SELLABLE stock = units in 'unassembled' or 'assembled'. Reserved units are committed to
--  a customer, on-hold units are in repair, and sold units are gone — none are sellable.
--
--  Reuses the existing motorcycle permissions (motorcycle.read to view, motorcycle.config
--  to tune), so no new permission is seeded. Additive table only; idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS motorcycle_reorder_points (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    model_id      UUID NOT NULL REFERENCES motorcycle_models(id) ON DELETE CASCADE,
    -- NULL colour = the model-wide default for colours without their own row.
    colour_id     UUID REFERENCES motorcycle_colours(id) ON DELETE CASCADE,
    reorder_point INTEGER NOT NULL CHECK (reorder_point >= 0),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One row per model+colour. Two partial indexes because NULL never equals NULL in a
-- UNIQUE constraint, so the model-wide default needs its own guard.
CREATE UNIQUE INDEX IF NOT EXISTS uq_moto_reorder_model_colour
    ON motorcycle_reorder_points (tenant_id, model_id, colour_id) WHERE colour_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_moto_reorder_model_default
    ON motorcycle_reorder_points (tenant_id, model_id) WHERE colour_id IS NULL;

DROP TRIGGER IF EXISTS trg_moto_reorder_points_updated_at ON motorcycle_reorder_points;
CREATE TRIGGER trg_moto_reorder_points_updated_at
    BEFORE UPDATE ON motorcycle_reorder_points FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['motorcycle_reorder_points']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY;', t);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING      (tenant_id = NULLIF(current_setting(''app.current_tenant'', true), '''')::uuid) '
                'WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant'', true), '''')::uuid);',
                t);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            -- Tuning config, not a ledger: a threshold may be changed or removed.
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_user;', t);
        END IF;
    END LOOP;
END
$$;

COMMENT ON TABLE motorcycle_reorder_points IS 'Sellable-stock threshold per motorcycle model (optionally per colour; NULL colour = model-wide default). Drives the "bike colours running low" alert. Separate from assembly_targets, which tunes assembly readiness rather than purchasing.';
