-- ============================================================================
--  Generic Data-Import framework + Inventory target  (additive, idempotent)
--
--  Backs the reusable import engine (first target: "inventory"; later suppliers,
--  customers, sales history, POs, ...). Tables:
--    import_jobs      one row per upload/import run (status + progress counts)
--    import_files     the uploaded bytes (1:1 with a job) — kept out of import_jobs
--                     so status polls / history lists never read the blob, and the
--                     background runner / retry can re-parse the original file
--    import_errors    per-row failures (row_number, sku, message) for error reports
--    import_mappings  remembered column maps per (tenant, target, header signature)
--
--  Also adds product-level unit_of_measure + currency (currency NULL => tenant
--  base_currency), products.created_by_import_job_id (rollback linkage), the
--  'initial_import' stock-movement type, and the data.import permission.
--
--  Idempotent: safe as a fresh-init script and as Alembic migration 0011.
-- ============================================================================

-- ---- Product schema extensions ---------------------------------------------
ALTER TABLE products ADD COLUMN IF NOT EXISTS unit_of_measure TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS currency        CHAR(3);  -- NULL => tenant.base_currency

-- ---- Stock-movement type: add 'initial_import' -----------------------------
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_movement_type_check;
ALTER TABLE stock_movements ADD  CONSTRAINT stock_movements_movement_type_check
    CHECK (movement_type IN
        ('receipt','issue','adjustment','transfer_in','transfer_out',
         'damage','reserve','unreserve','initial_import'));

-- ---- import_jobs -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_jobs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    target_key     TEXT NOT NULL,                 -- 'inventory', later 'suppliers', ...
    filename       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','completed','cancelled','failed')),
    total_rows     INT  NOT NULL DEFAULT 0,
    processed_rows INT  NOT NULL DEFAULT 0,
    imported_rows  INT  NOT NULL DEFAULT 0,
    skipped_rows   INT  NOT NULL DEFAULT 0,
    error_count    INT  NOT NULL DEFAULT 0,
    column_mapping JSONB,
    options        JSONB,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_import_jobs_tenant_time ON import_jobs (tenant_id, created_at DESC);

-- ---- import_files (uploaded bytes; 1:1 with a job) -------------------------
CREATE TABLE IF NOT EXISTS import_files (
    job_id       UUID PRIMARY KEY REFERENCES import_jobs(id) ON DELETE CASCADE,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    content      BYTEA NOT NULL,
    content_type TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- import_errors ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_errors (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    import_job_id UUID NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    row_number    INT  NOT NULL,
    sku           TEXT,
    error_message TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_import_errors_job ON import_errors (import_job_id, row_number);

-- ---- import_mappings (remembered column maps; used from Phase 2) -----------
CREATE TABLE IF NOT EXISTS import_mappings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    target_key       TEXT NOT NULL,
    header_signature TEXT NOT NULL,           -- stable hash of the source header set
    mapping          JSONB NOT NULL,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, target_key, header_signature)
);

-- ---- products.created_by_import_job_id (rollback linkage) ------------------
ALTER TABLE products ADD COLUMN IF NOT EXISTS created_by_import_job_id UUID
    REFERENCES import_jobs(id) ON DELETE SET NULL;

-- ---- RLS + app_user grants for the new tenant tables -----------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['import_jobs','import_files','import_errors','import_mappings']
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
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_user;', t);
        END IF;
    END LOOP;
END
$$;

-- ---- Permission: data.import (idempotent; also grants existing tenants) ----
INSERT INTO permissions (code, description) VALUES
    ('data.import', 'Import data from spreadsheets (products, inventory, ...)')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code = 'data.import'
WHERE r.is_system AND r.name IN ('Admin', 'Inventory Manager', 'Warehouse Manager')
ON CONFLICT DO NOTHING;
