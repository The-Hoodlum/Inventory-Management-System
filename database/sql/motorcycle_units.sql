-- ============================================================================
--  Motorcycle module: serialized-asset catalog + per-unit registry
--  (additive, idempotent)
--
--  Two layers, both tenant-scoped and industry-agnostic (nothing hard-coded to
--  any brand). Configured for motorcycles for this tenant, but the shape is a
--  generic "serialized asset" concept.
--
--  Layer 1 - reference catalog (admins configure these):
--    motorcycle_models    a sellable model (reuses brands + categories)
--    motorcycle_variants  a variant of a model
--    motorcycle_colours   a flat tenant colour list, shared across models
--
--  Layer 2 - per-unit master registry:
--    motorcycle_units         one permanent row per physical unit (by chassis)
--    motorcycle_unit_events   the unit's immutable lifecycle ledger
--
--  Selling a unit goes through the existing sales documents (reserved_ref -> a
--  sales order, sold_ref -> an invoice); there is no parallel sales path here.
--  Idempotent: safe as a fresh-init script and as an Alembic migration.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Layer 1: reference catalog
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS motorcycle_models (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    brand_id               UUID NOT NULL REFERENCES brands(id)     ON DELETE RESTRICT,
    name                   TEXT NOT NULL,
    category_id            UUID REFERENCES categories(id)          ON DELETE SET NULL,
    engine_cc              INT,
    default_selling_price  NUMERIC(18,4),
    specs                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active              BOOLEAN NOT NULL DEFAULT true,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, brand_id, name)
);
CREATE INDEX IF NOT EXISTS idx_motorcycle_models_tenant ON motorcycle_models (tenant_id);
CREATE INDEX IF NOT EXISTS idx_motorcycle_models_brand  ON motorcycle_models (brand_id);

DROP TRIGGER IF EXISTS trg_motorcycle_models_updated_at ON motorcycle_models;
CREATE TRIGGER trg_motorcycle_models_updated_at
    BEFORE UPDATE ON motorcycle_models FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS motorcycle_variants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id)            ON DELETE CASCADE,
    model_id    UUID NOT NULL REFERENCES motorcycle_models(id)  ON DELETE CASCADE,
    name        TEXT NOT NULL,
    specs       JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, model_id, name)
);
CREATE INDEX IF NOT EXISTS idx_motorcycle_variants_model ON motorcycle_variants (model_id);

DROP TRIGGER IF EXISTS trg_motorcycle_variants_updated_at ON motorcycle_variants;
CREATE TRIGGER trg_motorcycle_variants_updated_at
    BEFORE UPDATE ON motorcycle_variants FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS motorcycle_colours (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    hex_code    TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_motorcycle_colours_tenant ON motorcycle_colours (tenant_id);

DROP TRIGGER IF EXISTS trg_motorcycle_colours_updated_at ON motorcycle_colours;
CREATE TRIGGER trg_motorcycle_colours_updated_at
    BEFORE UPDATE ON motorcycle_colours FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Layer 2: per-unit registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS motorcycle_units (
    id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                     UUID NOT NULL REFERENCES tenants(id)             ON DELETE CASCADE,
    chassis_number                TEXT NOT NULL,
    engine_number                 TEXT,
    model_id                      UUID NOT NULL REFERENCES motorcycle_models(id)   ON DELETE RESTRICT,
    variant_id                    UUID REFERENCES motorcycle_variants(id)          ON DELETE SET NULL,
    colour_id                     UUID REFERENCES motorcycle_colours(id)           ON DELETE SET NULL,
    year                          INT,
    supplier_id                   UUID REFERENCES suppliers(id)                    ON DELETE SET NULL,
    container_ref                 TEXT,
    date_received                 DATE,
    branch_id                     UUID REFERENCES branches(id)                     ON DELETE SET NULL,
    warehouse_id                  UUID REFERENCES warehouses(id)                   ON DELETE SET NULL,
    internal_location             TEXT,
    -- Lifecycle state (state machine lives in app/motorcycles/domain/lifecycle.py).
    status                        TEXT NOT NULL DEFAULT 'received',
    inspection_status             TEXT NOT NULL DEFAULT 'pending',
    assembly_status               TEXT NOT NULL DEFAULT 'not_required',
    -- Serialized hold + sale linkage into the EXISTING sales documents.
    reserved_ref                  UUID REFERENCES sales_orders(id)                 ON DELETE SET NULL,
    sold_ref                      UUID REFERENCES invoices(id)                     ON DELETE SET NULL,
    customer_id                   UUID REFERENCES customers(id)                    ON DELETE SET NULL,
    selling_price                 NUMERIC(18,4),
    price_charged                 NUMERIC(18,4),
    payment_status                TEXT NOT NULL DEFAULT 'unpaid',
    -- Registration + warranty (fields future modules attach to; no logic here yet).
    registration_status           TEXT NOT NULL DEFAULT 'unregistered',
    registration_number           TEXT,
    registration_papers_received  BOOLEAN NOT NULL DEFAULT false,
    warranty_start                DATE,
    warranty_end                  DATE,
    version                       INT NOT NULL DEFAULT 0,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, chassis_number)
);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_tenant   ON motorcycle_units (tenant_id);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_status   ON motorcycle_units (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_model    ON motorcycle_units (model_id);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_branch   ON motorcycle_units (branch_id);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_customer ON motorcycle_units (customer_id);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_engine   ON motorcycle_units (tenant_id, engine_number);
CREATE INDEX IF NOT EXISTS idx_motorcycle_units_regno    ON motorcycle_units (tenant_id, registration_number);

DROP TRIGGER IF EXISTS trg_motorcycle_units_updated_at ON motorcycle_units;
CREATE TRIGGER trg_motorcycle_units_updated_at
    BEFORE UPDATE ON motorcycle_units FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The unit's immutable lifecycle ledger: one row per lifecycle event, each linked
-- to the source document that caused it where applicable. Append-only.
CREATE TABLE IF NOT EXISTS motorcycle_unit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id)           ON DELETE CASCADE,
    unit_id         UUID NOT NULL REFERENCES motorcycle_units(id)  ON DELETE CASCADE,
    event_type      TEXT NOT NULL,   -- created | status_change | reserved | released | sold | transfer | updated
    from_status     TEXT,
    to_status       TEXT,
    from_branch_id  UUID REFERENCES branches(id) ON DELETE SET NULL,
    to_branch_id    UUID REFERENCES branches(id) ON DELETE SET NULL,
    reference_type  TEXT,            -- sales_order | invoice | ...
    reference_id    UUID,
    note            TEXT,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_motorcycle_unit_events_unit ON motorcycle_unit_events (unit_id, created_at);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (same discipline as every other business table)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'motorcycle_models','motorcycle_variants','motorcycle_colours',
        'motorcycle_units','motorcycle_unit_events'
    ]
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

-- ---------------------------------------------------------------------------
-- Permissions + role grants
-- ---------------------------------------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('motorcycle.read',   'View motorcycle units and reference catalog'),
    ('motorcycle.manage', 'Create / update units and drive the lifecycle (reserve, sell, transfer)'),
    ('motorcycle.config', 'Manage the reference catalog (models, variants, colours)')
ON CONFLICT (code) DO NOTHING;

-- Admin: everything.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('motorcycle.read','motorcycle.manage','motorcycle.config')
WHERE r.is_system AND r.name = 'Admin'
ON CONFLICT DO NOTHING;

-- Branch Manager + Inventory Manager: full unit + catalog operations.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('motorcycle.read','motorcycle.manage','motorcycle.config')
WHERE r.is_system AND r.name IN ('Branch Manager','Inventory Manager')
ON CONFLICT DO NOTHING;

-- Warehouse Manager + Salesperson: manage units (assembly/inspection/reserve/sell/transfer), no catalog config.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('motorcycle.read','motorcycle.manage')
WHERE r.is_system AND r.name IN ('Warehouse Manager','Salesperson')
ON CONFLICT DO NOTHING;

-- Cashier, Finance, Procurement Manager, Viewer: read-only visibility.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'motorcycle.read'
WHERE r.is_system AND r.name IN ('Cashier','Finance','Procurement Manager','Viewer')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE motorcycle_models       IS 'Reference catalog: a sellable motorcycle model (tenant-scoped; reuses brands + categories).';
COMMENT ON TABLE motorcycle_variants     IS 'Reference catalog: a variant of a motorcycle model.';
COMMENT ON TABLE motorcycle_colours      IS 'Reference catalog: a flat tenant colour list shared across models.';
COMMENT ON TABLE motorcycle_units        IS 'Per-unit serialized registry: one permanent row per physical unit, tracked by chassis through its whole life.';
COMMENT ON TABLE motorcycle_unit_events  IS 'Immutable lifecycle ledger for a unit; each row links to the source document that caused it where applicable.';
