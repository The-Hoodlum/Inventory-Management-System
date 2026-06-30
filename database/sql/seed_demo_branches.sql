-- ============================================================================
--  DEMO SEED — branches + their locations for the "demo" tenant  (DATA, not code)
--
--  Promotes the demo tenant to a two-branch layout so the multi-branch transfer
--  flows are visible:
--
--      Solwezi  ── Main Warehouse · Cashier Room · Workshop · Showroom
--      Lusaka   ── Main Warehouse · Cashier Room · Workshop · Showroom
--
--  These are tenant CONFIGURATION records, deliberately kept out of application
--  code — every other tenant defines its own branches/locations (e.g. Store A,
--  Pharmacy Counter, Cold Room). Generic engine; site names are demo data only.
--
--  Depends on: branches.sql (branches table + warehouses.branch_id + backfill) and
--  seed_demo_locations.sql (the Solwezi-side locations already exist).
-- ============================================================================
DO $$
DECLARE
    v_tenant  UUID;
    v_solwezi UUID;
    v_lusaka  UUID;
BEGIN
    SELECT id INTO v_tenant FROM tenants WHERE slug = 'demo';
    IF v_tenant IS NULL THEN
        RETURN;  -- demo tenant not seeded (e.g. production); nothing to do
    END IF;

    -- 1) Branches (idempotent on (tenant_id, code)).
    INSERT INTO branches (tenant_id, code, name) VALUES (v_tenant, 'SOL', 'Solwezi')
        ON CONFLICT (tenant_id, code) DO NOTHING;
    INSERT INTO branches (tenant_id, code, name) VALUES (v_tenant, 'LUS', 'Lusaka')
        ON CONFLICT (tenant_id, code) DO NOTHING;
    SELECT id INTO v_solwezi FROM branches WHERE tenant_id = v_tenant AND code = 'SOL';
    SELECT id INTO v_lusaka  FROM branches WHERE tenant_id = v_tenant AND code = 'LUS';

    -- 2) Attach the existing demo locations to the Solwezi branch.
    UPDATE warehouses
       SET branch_id = v_solwezi
     WHERE tenant_id = v_tenant
       AND code IN ('WH-MAIN', 'WH-2', 'LOC-CASHIER', 'LOC-WORKSHOP', 'LOC-SHOWROOM');

    -- 3) Create the Lusaka location set (matched by code per tenant; safe to re-run).
    INSERT INTO warehouses (tenant_id, code, name, branch_id, warehouse_type)
    SELECT v_tenant, x.code, x.name, v_lusaka, x.wtype
    FROM (VALUES
        ('LUS-MAIN',     'Main Warehouse', 'main'),
        ('LUS-CASHIER',  'Cashier Room',   'counter'),
        ('LUS-WORKSHOP', 'Workshop',       'store'),
        ('LUS-SHOWROOM', 'Showroom',       'store')
    ) AS x(code, name, wtype)
    WHERE NOT EXISTS (
        SELECT 1 FROM warehouses w WHERE w.tenant_id = v_tenant AND w.code = x.code
    );

    -- 4) Drop the now-empty default "Main Branch" left by the generic backfill.
    DELETE FROM branches b
     WHERE b.tenant_id = v_tenant AND b.code = 'MAIN'
       AND NOT EXISTS (SELECT 1 FROM warehouses w WHERE w.branch_id = b.id);
END $$;
