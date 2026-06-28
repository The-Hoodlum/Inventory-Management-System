-- ============================================================================
--  Branches  (additive, idempotent)  — first-class, tenant-scoped branch entity
--
--  A BRANCH is a physical site (e.g. a town/depot); a LOCATION is a stock area
--  within it (warehouse, counter, shop floor, …). Until now "branch" was only a
--  free-text label on `warehouses`; this promotes it to a real, configurable
--  entity so the platform can key inventory / transfers / reports on
--  tenant_id + branch_id + location_id.
--
--    branches            one row per branch (tenant-scoped, code unique per tenant)
--    warehouses.branch_id every location now belongs to exactly one branch
--
--  Backfill is automatic and idempotent: each distinct existing `warehouses.branch`
--  label becomes a branch; any location with no label is attached to a per-tenant
--  default "Main Branch". Generic + industry-agnostic (no hard-coded site names —
--  demo sites live in seed_demo_branches.sql).
-- ============================================================================

CREATE TABLE IF NOT EXISTS branches (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);
CREATE INDEX IF NOT EXISTS idx_branches_tenant ON branches (tenant_id);

-- Auto-maintain updated_at (function defined in schema.sql, applied first at init).
DROP TRIGGER IF EXISTS trg_branches_updated_at ON branches;
CREATE TRIGGER trg_branches_updated_at
    BEFORE UPDATE ON branches FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Every location belongs to a branch (nullable for back-compat; always populated by backfill).
ALTER TABLE warehouses
    ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS idx_warehouses_branch ON warehouses (branch_id);

-- ---- Backfill (idempotent) -------------------------------------------------
DO $$
DECLARE r RECORD;
BEGIN
    -- 1) Promote each distinct non-empty branch label to a real branch.
    FOR r IN
        SELECT DISTINCT tenant_id, btrim(branch) AS label
        FROM warehouses
        WHERE branch IS NOT NULL AND btrim(branch) <> ''
    LOOP
        INSERT INTO branches (tenant_id, code, name)
        VALUES (
            r.tenant_id,
            upper(left(regexp_replace(r.label, '\s+', '-', 'g'), 60)),
            r.label
        )
        ON CONFLICT (tenant_id, code) DO NOTHING;
    END LOOP;

    UPDATE warehouses w
       SET branch_id = b.id
      FROM branches b
     WHERE w.branch_id IS NULL
       AND w.branch IS NOT NULL AND btrim(w.branch) <> ''
       AND b.tenant_id = w.tenant_id
       AND b.name = btrim(w.branch);

    -- 2) Any remaining (label-less) location -> a per-tenant default "Main Branch".
    INSERT INTO branches (tenant_id, code, name)
    SELECT DISTINCT w.tenant_id, 'MAIN', 'Main Branch'
    FROM warehouses w
    WHERE w.branch_id IS NULL
    ON CONFLICT (tenant_id, code) DO NOTHING;

    UPDATE warehouses w
       SET branch_id = b.id
      FROM branches b
     WHERE w.branch_id IS NULL
       AND b.tenant_id = w.tenant_id
       AND b.code = 'MAIN';
END $$;

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
BEGIN
    ALTER TABLE branches ENABLE ROW LEVEL SECURITY;
    ALTER TABLE branches FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'branches' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON branches
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON branches TO app_user;
    END IF;
END
$$;

COMMENT ON TABLE  branches           IS 'First-class, tenant-scoped branch (site). Locations (warehouses) belong to a branch.';
COMMENT ON COLUMN warehouses.branch_id IS 'The branch (site) this location belongs to.';
