-- ============================================================================
--  Motorcycle service follow-up — track when a SOLD bike is next due for service so
--  the shop can call the customer back.
--
--  Three additive pieces, no existing data changed:
--
--    1. motorcycle_units.service_usage — how hard THIS bike is ridden. One of
--       light / medium / heavy (commuting / delivery / rural-farm), which scales the
--       service interval (heavy wears faster -> due sooner). Defaults to 'medium'.
--
--    2. motorcycle_service_plans — the per-model service schedule (an ordered list of
--       stages, each a gap-in-days from the previous service). Editable per model;
--       model_id NULL is the tenant-wide default. When no row matches, the app falls
--       back to module defaults (app/service_followup/domain/schedule.py). Mirrors the
--       assembly_targets "override table + code default" pattern.
--
--    3. motorcycle_service_records — an append-only log of services actually performed
--       on a unit. "Next due" is computed from the last record (or the sale date) plus
--       the next stage's usage-scaled gap. This table never writes stock — it is a
--       customer-care record, not an inventory or sales document.
--
--  Idempotent. Reuses the existing motorcycle permissions (motorcycle.read to view,
--  motorcycle.manage to log a service / set usage, motorcycle.config to edit the
--  schedule), so no new permission is seeded here.
-- ============================================================================

-- 1. Per-unit usage profile ---------------------------------------------------
ALTER TABLE motorcycle_units
    ADD COLUMN IF NOT EXISTS service_usage TEXT NOT NULL DEFAULT 'medium';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'motorcycle_units_service_usage_ck'
    ) THEN
        ALTER TABLE motorcycle_units
            ADD CONSTRAINT motorcycle_units_service_usage_ck
            CHECK (service_usage IN ('light', 'medium', 'heavy'));
    END IF;
END
$$;

COMMENT ON COLUMN motorcycle_units.service_usage IS
    'How hard this bike is ridden (light=commuting / medium=delivery / heavy=rural-farm). Scales the service interval; defaults to medium.';

-- 2. Per-model service schedule (editable; NULL model = tenant default) --------
CREATE TABLE IF NOT EXISTS motorcycle_service_plans (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- NULL = the tenant-wide default schedule used when a model has no override.
    model_id    UUID REFERENCES motorcycle_models(id) ON DELETE CASCADE,
    -- Ordered list of stage objects, each with the keys sequence, label and interval_days.
    -- Each interval_days is the gap from the PREVIOUS service (the first from the sale).
    -- The last stage's interval repeats for every service beyond the list.
    stages      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One override per model, and one tenant-wide default (NULL model). NULLs are otherwise
-- distinct in a plain UNIQUE, so the default gets its own partial unique index.
CREATE UNIQUE INDEX IF NOT EXISTS uq_service_plans_model
    ON motorcycle_service_plans (tenant_id, model_id) WHERE model_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_service_plans_default
    ON motorcycle_service_plans (tenant_id) WHERE model_id IS NULL;

DROP TRIGGER IF EXISTS trg_service_plans_updated_at ON motorcycle_service_plans;
CREATE TRIGGER trg_service_plans_updated_at
    BEFORE UPDATE ON motorcycle_service_plans FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 3. Append-only log of services performed ------------------------------------
CREATE TABLE IF NOT EXISTS motorcycle_service_records (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    unit_id       UUID NOT NULL REFERENCES motorcycle_units(id) ON DELETE CASCADE,
    -- Which service in the schedule this was (1st, 2nd, ...). Recorded at log time.
    sequence      INTEGER NOT NULL CHECK (sequence >= 1),
    label         TEXT,
    service_date  DATE NOT NULL,
    note          TEXT,
    performed_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_service_records_unit
    ON motorcycle_service_records (unit_id, service_date);
CREATE INDEX IF NOT EXISTS idx_service_records_tenant
    ON motorcycle_service_records (tenant_id, service_date DESC);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants. Explicit per-table blocks (no format() / no percent signs —
-- this file is also run through SQLAlchemy op.execute(), which treats a percent as a
-- bind-parameter marker and fails on it).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    ALTER TABLE motorcycle_service_plans ENABLE ROW LEVEL SECURITY;
    ALTER TABLE motorcycle_service_plans FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'motorcycle_service_plans' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON motorcycle_service_plans
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;

    ALTER TABLE motorcycle_service_records ENABLE ROW LEVEL SECURITY;
    ALTER TABLE motorcycle_service_records FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'motorcycle_service_records' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON motorcycle_service_records
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON motorcycle_service_plans   TO app_user;
        GRANT SELECT, INSERT, UPDATE, DELETE ON motorcycle_service_records TO app_user;
    END IF;
END
$$;

COMMENT ON TABLE motorcycle_service_plans IS 'Per-model service schedule (ordered stages, gap-in-days each). NULL model_id is the tenant default; app falls back to module defaults when absent.';
COMMENT ON TABLE motorcycle_service_records IS 'Append-only log of services performed on a sold motorcycle unit. Drives the next-due calculation; never writes stock.';
