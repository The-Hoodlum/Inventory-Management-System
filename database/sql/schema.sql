-- ============================================================================
--  INVENTORY MANAGEMENT & PROCUREMENT PLATFORM
--  Canonical PostgreSQL schema (PostgreSQL 16+)
--
--  This file is the human-readable source of truth for the database schema.
--  It is executed verbatim by Alembic migration 0001_initial_schema.py.
--  Run directly for a quick start:   psql "$DATABASE_URL" -f sql/schema.sql
--
--  Conventions:
--    * UUID primary keys (gen_random_uuid)
--    * Money / quantities: NUMERIC(18,4)  (NEVER float)
--    * FX rates: NUMERIC(18,6)
--    * Timestamps: TIMESTAMPTZ, default now()
--    * Multi-tenant: tenant_id on every business table + Row-Level Security
--    * Soft deletes on catalog tables; stock & PO records are never hard-deleted
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- fuzzy SKU / name search (GIN trigram)
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive email / name

-- ----------------------------------------------------------------------------
-- 1. SHARED FUNCTIONS
-- ----------------------------------------------------------------------------
-- Auto-maintain updated_at on UPDATE.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- ============================================================================
-- 2. TENANCY & IDENTITY
-- ============================================================================

CREATE TABLE tenants (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT        NOT NULL,
    slug           TEXT        NOT NULL UNIQUE,
    base_currency  CHAR(3)     NOT NULL DEFAULT 'USD',
    fx_rate        NUMERIC(18,6) NOT NULL DEFAULT 1,    -- base-currency units per 1 foreign unit (tenant default)
    vat_rate       NUMERIC(6,4)  NOT NULL DEFAULT 0     -- e.g. 0.1600 for 16%
                   CHECK (vat_rate >= 0 AND vat_rate < 1),
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Identity / RBAC tables are intentionally NOT under Row-Level Security.
-- The trusted auth service resolves the tenant during login (before any GUC is
-- set), and tenant isolation for users is enforced by the (tenant_id, email)
-- unique key + the application/repository layer. See README "RLS scope".
CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email          CITEXT NOT NULL,
    password_hash  TEXT   NOT NULL,
    full_name      TEXT   NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at  TIMESTAMPTZ,
    failed_login_count   INT NOT NULL DEFAULT 0,
    locked_until         TIMESTAMPTZ,
    last_failed_login_at TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);
CREATE INDEX idx_users_tenant ON users (tenant_id);

-- Server-side refresh-token sessions (rotation + revocation + reuse detection).
-- NOT under RLS: refresh runs before any tenant context exists.
CREATE TABLE refresh_sessions (
    id           UUID PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    family_id    UUID NOT NULL,
    issued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    replaced_by  UUID,
    user_agent   TEXT,
    ip_address   INET,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_sessions_user   ON refresh_sessions (user_id);
CREATE INDEX idx_refresh_sessions_family ON refresh_sessions (family_id);

CREATE TABLE roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = global system role
    name        TEXT NOT NULL,
    description TEXT,
    is_system   BOOLEAN NOT NULL DEFAULT FALSE
);
-- A tenant cannot have two roles with the same name; system roles are unique by name.
CREATE UNIQUE INDEX uq_roles_tenant_name ON roles (tenant_id, name) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX uq_roles_system_name ON roles (name)            WHERE tenant_id IS NULL;

CREATE TABLE permissions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        TEXT NOT NULL UNIQUE,   -- e.g. 'product.create', 'po.approve'
    description TEXT
);

CREATE TABLE role_permissions (
    role_id       UUID NOT NULL REFERENCES roles(id)       ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);
CREATE INDEX idx_role_permissions_permission ON role_permissions (permission_id);

CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX idx_user_roles_role ON user_roles (role_id);

CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,             -- create | update | delete | approve | receive | ...
    entity_type TEXT NOT NULL,             -- 'product', 'purchase_order', ...
    entity_id   UUID,
    changes     JSONB,                     -- { "before": {...}, "after": {...} }
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_tenant_time ON audit_logs (tenant_id, created_at DESC);
CREATE INDEX idx_audit_entity      ON audit_logs (entity_type, entity_id);

-- ============================================================================
-- 3. CATALOG
-- ============================================================================

CREATE TABLE categories (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    parent_id  UUID REFERENCES categories(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name, parent_id)
);
CREATE INDEX idx_categories_tenant ON categories (tenant_id);
CREATE INDEX idx_categories_parent ON categories (parent_id);

CREATE TABLE brands (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX idx_brands_tenant ON brands (tenant_id);

CREATE TABLE suppliers (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                   TEXT NOT NULL,
    contact_person         TEXT,
    email                  CITEXT,
    phone                  TEXT,
    country                TEXT,
    currency               CHAR(3) NOT NULL DEFAULT 'USD',
    payment_terms          TEXT,                         -- 'Net 30', '50% deposit', ...
    default_lead_time_days INT  NOT NULL DEFAULT 30 CHECK (default_lead_time_days >= 0),
    status                 TEXT NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active','inactive')),
    deleted_at             TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Name unique per tenant among non-deleted suppliers (a deleted name can be reused).
CREATE UNIQUE INDEX uq_suppliers_tenant_name ON suppliers (tenant_id, name) WHERE deleted_at IS NULL;
CREATE INDEX idx_suppliers_tenant ON suppliers (tenant_id) WHERE deleted_at IS NULL;

CREATE TABLE products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sku                 TEXT NOT NULL,
    barcode             TEXT,
    name                TEXT NOT NULL,
    description         TEXT,
    category_id         UUID REFERENCES categories(id) ON DELETE SET NULL,
    brand_id            UUID REFERENCES brands(id)     ON DELETE SET NULL,
    primary_supplier_id UUID REFERENCES suppliers(id)  ON DELETE SET NULL,
    cost_price          NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (cost_price    >= 0),
    selling_price       NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (selling_price >= 0),
    units_per_carton    INT NOT NULL DEFAULT 1 CHECK (units_per_carton >= 1),
    moq                 INT NOT NULL DEFAULT 0 CHECK (moq >= 0),
    lead_time_days      INT NOT NULL DEFAULT 30 CHECK (lead_time_days >= 0),
    -- Future pallet / container fields (stored from day one, unused by MVP algorithms)
    weight_per_unit     NUMERIC(18,4) CHECK (weight_per_unit    IS NULL OR weight_per_unit    >= 0),
    volume_per_unit     NUMERIC(18,6) CHECK (volume_per_unit    IS NULL OR volume_per_unit    >= 0),
    weight_per_carton   NUMERIC(18,4) CHECK (weight_per_carton  IS NULL OR weight_per_carton  >= 0),
    volume_per_carton   NUMERIC(18,6) CHECK (volume_per_carton  IS NULL OR volume_per_carton  >= 0),
    cartons_per_pallet  INT           CHECK (cartons_per_pallet IS NULL OR cartons_per_pallet > 0),
    -- Reorder parameters (NULL => computed by the reorder engine; non-NULL => manual override)
    reorder_point       INT CHECK (reorder_point IS NULL OR reorder_point >= 0),
    safety_stock        INT CHECK (safety_stock  IS NULL OR safety_stock  >= 0),
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','inactive','discontinued')),
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- SKU unique per tenant among non-deleted products; barcode likewise when present.
CREATE UNIQUE INDEX uq_products_tenant_sku     ON products (tenant_id, sku)     WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_products_tenant_barcode ON products (tenant_id, barcode) WHERE deleted_at IS NULL AND barcode IS NOT NULL;
CREATE INDEX idx_products_tenant   ON products (tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_products_category ON products (category_id);
CREATE INDEX idx_products_brand    ON products (brand_id);
CREATE INDEX idx_products_supplier ON products (primary_supplier_id);
CREATE INDEX idx_products_name_trgm ON products USING gin (name gin_trgm_ops);

CREATE TABLE supplier_products (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id)   ON DELETE CASCADE,
    supplier_id      UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    product_id       UUID NOT NULL REFERENCES products(id)  ON DELETE CASCADE,
    supplier_sku     TEXT,
    cost_price       NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    currency         CHAR(3) NOT NULL DEFAULT 'USD',
    moq              INT NOT NULL DEFAULT 0 CHECK (moq >= 0),
    lead_time_days   INT NOT NULL DEFAULT 30 CHECK (lead_time_days >= 0),
    units_per_carton INT CHECK (units_per_carton IS NULL OR units_per_carton >= 1),
    is_preferred     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (supplier_id, product_id)
);
CREATE INDEX idx_supplier_products_product  ON supplier_products (product_id);
CREATE INDEX idx_supplier_products_tenant   ON supplier_products (tenant_id);

-- ============================================================================
-- 4. LOCATIONS
-- ============================================================================

CREATE TABLE warehouses (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    address    TEXT,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_warehouses_tenant ON warehouses (tenant_id);

-- ============================================================================
-- 5. STOCK
-- ============================================================================

-- One row per (product, warehouse). qty_available is a STORED generated column
-- so it can never drift from its components and can be indexed/filtered directly.
CREATE TABLE inventory (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    product_id    UUID NOT NULL REFERENCES products(id)   ON DELETE CASCADE,
    warehouse_id  UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    qty_on_hand   NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (qty_on_hand  >= 0),
    qty_reserved  NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (qty_reserved >= 0),
    qty_damaged   NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (qty_damaged  >= 0),
    qty_available NUMERIC(18,4) GENERATED ALWAYS AS (qty_on_hand - qty_reserved - qty_damaged) STORED,
    version       INT NOT NULL DEFAULT 0,   -- optimistic lock (app-managed)
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, warehouse_id)
);
CREATE INDEX idx_inventory_tenant_wh ON inventory (tenant_id, warehouse_id);
CREATE INDEX idx_inventory_available ON inventory (qty_available);

-- Append-only ledger. Sign convention: quantity is POSITIVE for inflows
-- (receipt, transfer_in, unreserve) and NEGATIVE for outflows (issue,
-- transfer_out, damage, reserve). The inventory table is the running balance
-- maintained transactionally alongside each movement insert.
CREATE TABLE stock_movements (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    product_id        UUID NOT NULL REFERENCES products(id)   ON DELETE RESTRICT,
    warehouse_id      UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    movement_type     TEXT NOT NULL CHECK (movement_type IN
                        ('receipt','issue','adjustment','transfer_in','transfer_out',
                         'damage','reserve','unreserve')),
    quantity          NUMERIC(18,4) NOT NULL,           -- signed
    reference_type    TEXT,                             -- 'purchase_order','sales_order','manual',...
    reference_id      UUID,
    from_warehouse_id UUID REFERENCES warehouses(id) ON DELETE SET NULL,
    to_warehouse_id   UUID REFERENCES warehouses(id) ON DELETE SET NULL,
    unit_cost         NUMERIC(18,4) CHECK (unit_cost IS NULL OR unit_cost >= 0),
    reason            TEXT,
    user_id           UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_movements_product_time ON stock_movements (product_id, created_at DESC);
CREATE INDEX idx_movements_tenant_time  ON stock_movements (tenant_id, created_at DESC);
CREATE INDEX idx_movements_warehouse    ON stock_movements (warehouse_id);
CREATE INDEX idx_movements_reference    ON stock_movements (reference_type, reference_id);

-- ============================================================================
-- 6. DEMAND  (feeds the reorder engine)
-- ============================================================================

CREATE TABLE sales_daily (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    product_id   UUID NOT NULL REFERENCES products(id)   ON DELETE CASCADE,
    warehouse_id UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    sale_date    DATE NOT NULL,
    qty_sold     NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (qty_sold >= 0),
    UNIQUE (product_id, warehouse_id, sale_date)
);
CREATE INDEX idx_sales_product_date ON sales_daily (product_id, sale_date DESC);
CREATE INDEX idx_sales_tenant       ON sales_daily (tenant_id);

-- ============================================================================
-- 7. PROCUREMENT
-- ============================================================================

-- Per-tenant, per-year monotonic counter backing next_po_number().
CREATE TABLE po_counters (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    year      INT  NOT NULL,
    last_seq  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, year)
);

-- Concurrency-safe PO number generator: 'PO-YYYY-00042'. The upsert locks the
-- counter row, so two concurrent transactions cannot mint the same number.
CREATE OR REPLACE FUNCTION next_po_number(p_tenant UUID)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    v_year INT := EXTRACT(YEAR FROM now())::int;
    v_seq  INT;
BEGIN
    INSERT INTO po_counters (tenant_id, year, last_seq)
    VALUES (p_tenant, v_year, 1)
    ON CONFLICT (tenant_id, year)
    DO UPDATE SET last_seq = po_counters.last_seq + 1
    RETURNING last_seq INTO v_seq;

    RETURN 'PO-' || v_year::text || '-' || lpad(v_seq::text, 5, '0');
END;
$$;

CREATE TABLE purchase_orders (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    po_number     TEXT NOT NULL,
    supplier_id   UUID NOT NULL REFERENCES suppliers(id)  ON DELETE RESTRICT,
    warehouse_id  UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft','pending_approval','approved','rejected',
                     'sent','partially_received','received','cancelled')),
    currency      CHAR(3) NOT NULL DEFAULT 'USD',
    fx_rate       NUMERIC(18,6) NOT NULL DEFAULT 1 CHECK (fx_rate > 0),
    subtotal      NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    tax           NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (tax      >= 0),
    total         NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (total    >= 0),
    notes         TEXT,
    expected_date DATE,
    created_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at   TIMESTAMPTZ,
    version       INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, po_number)
);
CREATE INDEX idx_po_tenant_status ON purchase_orders (tenant_id, status);
CREATE INDEX idx_po_supplier      ON purchase_orders (supplier_id);
CREATE INDEX idx_po_warehouse     ON purchase_orders (warehouse_id);

CREATE TABLE purchase_order_lines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- denormalized for RLS
    po_id           UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_id      UUID NOT NULL REFERENCES products(id)        ON DELETE RESTRICT,
    ordered_qty     NUMERIC(18,4) NOT NULL CHECK (ordered_qty > 0),
    ordered_cartons INT,
    unit_cost       NUMERIC(18,4) NOT NULL CHECK (unit_cost >= 0),
    line_total      NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (line_total >= 0),
    received_qty    NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (received_qty >= 0),
    UNIQUE (po_id, product_id),
    CHECK (received_qty <= ordered_qty)
);
CREATE INDEX idx_po_lines_po       ON purchase_order_lines (po_id);
CREATE INDEX idx_po_lines_product  ON purchase_order_lines (product_id);
CREATE INDEX idx_po_lines_tenant   ON purchase_order_lines (tenant_id);

CREATE TABLE reorder_recommendations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    product_id          UUID NOT NULL REFERENCES products(id)   ON DELETE CASCADE,
    warehouse_id        UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    supplier_id         UUID REFERENCES suppliers(id) ON DELETE SET NULL,
    available_qty       NUMERIC(18,4) NOT NULL,
    on_order_qty        NUMERIC(18,4) NOT NULL DEFAULT 0,
    avg_daily_demand    NUMERIC(18,4) NOT NULL,
    reorder_point       NUMERIC(18,4) NOT NULL,
    safety_stock        NUMERIC(18,4) NOT NULL,
    recommended_qty     NUMERIC(18,4) NOT NULL CHECK (recommended_qty >= 0),
    recommended_cartons INT NOT NULL CHECK (recommended_cartons >= 0),
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','accepted','dismissed','ordered')),
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_reco_tenant_status ON reorder_recommendations (tenant_id, status);
CREATE INDEX idx_reco_product       ON reorder_recommendations (product_id);
CREATE INDEX idx_reco_warehouse     ON reorder_recommendations (warehouse_id);

-- ============================================================================
-- 8. TRIGGERS (auto updated_at)
-- ============================================================================
CREATE TRIGGER trg_tenants_updated_at           BEFORE UPDATE ON tenants           FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_users_updated_at             BEFORE UPDATE ON users             FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_suppliers_updated_at         BEFORE UPDATE ON suppliers         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_products_updated_at          BEFORE UPDATE ON products          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_supplier_products_updated_at BEFORE UPDATE ON supplier_products FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_inventory_updated_at         BEFORE UPDATE ON inventory         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_purchase_orders_updated_at   BEFORE UPDATE ON purchase_orders   FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 9. ROW-LEVEL SECURITY (tenant isolation on business-data tables)
--
-- The application connects as a NON-superuser role (see README) and runs, per
-- request:   SET app.current_tenant = '<tenant-uuid>';
-- FORCE ROW LEVEL SECURITY ensures even the table owner is subject to the policy.
-- current_setting(..., true) is missing-ok so an unset GUC yields zero rows
-- instead of an error.
-- ============================================================================
DO $$
DECLARE
    t TEXT;
    rls_tables TEXT[] := ARRAY[
        'categories','brands','suppliers','products','supplier_products',
        'warehouses','inventory','stock_movements','sales_daily',
        'purchase_orders','purchase_order_lines','reorder_recommendations',
        'audit_logs','po_counters'
    ];
BEGIN
    FOREACH t IN ARRAY rls_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY;', t);
        EXECUTE format($pol$
            CREATE POLICY tenant_isolation ON %I
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
        $pol$, t);
    END LOOP;
END;
$$;

-- ============================================================================
-- 10. COLUMN / TABLE COMMENTS (in-database data dictionary)
-- ============================================================================
COMMENT ON COLUMN tenants.fx_rate                 IS 'Tenant default: base-currency units per 1 unit of foreign currency.';
COMMENT ON COLUMN tenants.vat_rate                IS 'Default VAT/GST as a fraction, e.g. 0.16 = 16%.';
COMMENT ON COLUMN inventory.qty_available         IS 'Generated: qty_on_hand - qty_reserved - qty_damaged. Never written directly.';
COMMENT ON COLUMN inventory.version               IS 'Optimistic lock; app updates with WHERE version = <expected>.';
COMMENT ON COLUMN stock_movements.quantity        IS 'Signed: positive = inflow, negative = outflow.';
COMMENT ON COLUMN products.reorder_point          IS 'NULL = computed by reorder engine; non-NULL = manual override.';
COMMENT ON COLUMN products.units_per_carton       IS 'Pack size used for full-carton rounding (Inventory Rule #1).';
COMMENT ON COLUMN products.moq                    IS 'Default minimum order quantity (Rule #2). Supplier-specific MOQ lives in supplier_products.';
COMMENT ON TABLE  stock_movements                 IS 'Append-only inventory ledger; the source of truth for stock history.';
COMMENT ON TABLE  supplier_products               IS 'Per-supplier cost / MOQ / lead time / pack size for multi-sourced products.';
COMMENT ON FUNCTION next_po_number(UUID)          IS 'Returns the next per-tenant PO number, format PO-YYYY-00001.';

-- ============================================================================
--  END OF SCHEMA
-- ============================================================================
