-- ============================================================================
--  Motorcycle Lifecycle  —  SERIALIZED-UNIT registry  (additive, idempotent)
--
--  A serialized asset registry: each physical unit is ONE permanent record tracked
--  by chassis number through its whole life (received -> … -> warranty_active).
--  This is GENERIC — a "serialized asset" concept; nothing motorcycle/TVS-specific
--  is hard-coded (model/variant/colour/year are free tenant data). It is DISTINCT
--  from fungible parts inventory: a unit is not a quantity, so it is NOT tracked in
--  `inventory`/`stock_movements`; instead each unit keeps its OWN immutable lifecycle
--  ledger (motorcycle_unit_events).
--
--  Integration (no parallel paths):
--    * Selling goes through the EXISTING sales documents — the unit links to the
--      sales order / invoice / customer that sold it (reserved_sales_order_id,
--      invoice_id, customer_id). A serialized hold is "this exact chassis for this
--      customer", a different cardinality than the fungible qty_reserved counter,
--      so the hold lives on the unit (+ its sales-order link), not in `inventory`.
--    * A branch move is a serialized transfer recorded as a `transfer` event with
--      from/to branch+location — the transfer CONCEPT (audited, two-sided), reusing
--      the unit's own ledger rather than the fungible stock-transfer engine which
--      cannot represent a single serialized unit.
--
--  tenant_id + branch_id everywhere; RLS-isolated; optimistic-locked (version).
-- ============================================================================

-- ---- Units -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS motorcycle_units (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id)   ON DELETE CASCADE,
    chassis_number  TEXT NOT NULL,
    engine_number   TEXT,
    -- Free, tenant-configurable descriptors (no enumerated motorcycle values here).
    model           TEXT,
    variant         TEXT,
    colour          TEXT,
    year            INT,
    supplier_id     UUID REFERENCES suppliers(id)  ON DELETE SET NULL,
    container_ref   TEXT,
    date_received   DATE,
    -- Where the unit physically is (tenant -> branch -> location).
    branch_id       UUID REFERENCES branches(id)   ON DELETE RESTRICT,
    warehouse_id    UUID REFERENCES warehouses(id) ON DELETE RESTRICT,
    internal_location TEXT,
    -- Lifecycle position (state machine enforced in the service; see domain/lifecycle.py).
    status          TEXT NOT NULL DEFAULT 'received' CHECK (status IN (
                      'received','assembly_required','in_assembly','assembled','inspected',
                      'reserved','sold','delivered','registered','warranty_active','cancelled')),
    inspection_status TEXT NOT NULL DEFAULT 'pending'
                      CHECK (inspection_status IN ('pending','passed','failed')),
    assembly_status   TEXT NOT NULL DEFAULT 'not_required'
                      CHECK (assembly_status IN ('not_required','required','in_progress','done')),
    -- Reservation / sale linkage — money flows through the existing sales documents.
    reserved        BOOLEAN NOT NULL DEFAULT FALSE,
    reserved_sales_order_id UUID REFERENCES sales_orders(id) ON DELETE SET NULL,
    sold            BOOLEAN NOT NULL DEFAULT FALSE,
    invoice_id      UUID REFERENCES invoices(id)   ON DELETE SET NULL,
    customer_id     UUID REFERENCES customers(id)  ON DELETE SET NULL,
    selling_price   NUMERIC(18,4) NOT NULL DEFAULT 0,
    price_charged   NUMERIC(18,4) NOT NULL DEFAULT 0,
    -- Seams for out-of-scope modules (instalments, registration workflow, warranty claims).
    payment_status  TEXT NOT NULL DEFAULT 'unpaid'
                      CHECK (payment_status IN ('unpaid','partial','paid')),
    registration_status TEXT NOT NULL DEFAULT 'unregistered'
                      CHECK (registration_status IN ('unregistered','pending','registered')),
    registration_number TEXT,
    registration_papers_received BOOLEAN NOT NULL DEFAULT FALSE,
    warranty_start  DATE,
    warranty_end    DATE,
    notes           TEXT,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    version         INT  NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, chassis_number)
);
CREATE INDEX IF NOT EXISTS idx_moto_units_tenant_status ON motorcycle_units (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_moto_units_branch  ON motorcycle_units (branch_id);
CREATE INDEX IF NOT EXISTS idx_moto_units_customer ON motorcycle_units (customer_id);
CREATE INDEX IF NOT EXISTS idx_moto_units_model   ON motorcycle_units (tenant_id, model);
-- Fast exact lookups for global search (chassis / engine / registration).
CREATE INDEX IF NOT EXISTS idx_moto_units_engine  ON motorcycle_units (tenant_id, engine_number);
CREATE INDEX IF NOT EXISTS idx_moto_units_regno   ON motorcycle_units (tenant_id, registration_number);

-- ---- Immutable per-unit lifecycle ledger -----------------------------------
CREATE TABLE IF NOT EXISTS motorcycle_unit_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id)            ON DELETE CASCADE,
    unit_id       UUID NOT NULL REFERENCES motorcycle_units(id)   ON DELETE CASCADE,
    event_type    TEXT NOT NULL,            -- 'created' | 'status_change' | 'reserved' | 'sold' | 'transfer' | 'note'
    from_status   TEXT,
    to_status     TEXT,
    from_branch_id UUID REFERENCES branches(id) ON DELETE SET NULL,
    to_branch_id   UUID REFERENCES branches(id) ON DELETE SET NULL,
    reference_type TEXT,                     -- e.g. 'sales_order' | 'invoice'
    reference_id   UUID,                     -- the linked source document
    note          TEXT,
    user_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_moto_events_unit ON motorcycle_unit_events (unit_id, created_at);

-- ---- updated_at trigger ----------------------------------------------------
DROP TRIGGER IF EXISTS trg_motorcycle_units_updated_at ON motorcycle_units;
CREATE TRIGGER trg_motorcycle_units_updated_at BEFORE UPDATE ON motorcycle_units
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['motorcycle_units','motorcycle_unit_events']
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

-- ---- Permissions: view + manage the serialized-unit registry ---------------
INSERT INTO permissions (code, description) VALUES
    ('motorcycle.read',   'View the serialized-unit (motorcycle) registry'),
    ('motorcycle.manage', 'Create, edit, transition, reserve/sell and transfer serialized units')
ON CONFLICT (code) DO NOTHING;

-- Read for operational roles; manage for the roles that run the registry. Admin (full
-- access) is granted both. Idempotent.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'motorcycle.read'
WHERE r.is_system AND r.name IN
    ('Admin','Branch Manager','Warehouse Manager','Salesperson','Finance','Viewer')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'motorcycle.manage'
WHERE r.is_system AND r.name IN ('Admin','Branch Manager','Warehouse Manager')
ON CONFLICT DO NOTHING;
