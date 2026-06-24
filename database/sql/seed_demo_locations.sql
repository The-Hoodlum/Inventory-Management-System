-- ============================================================================
--  DEMO SEED — extra stock locations for the "demo" tenant  (DATA, not app code)
--
--  Adds a few internal stock locations so the multi-location flows are visible in
--  the demo. These are tenant CONFIGURATION records, deliberately kept out of
--  application code — every other tenant defines its own locations (e.g. Store A,
--  Pharmacy Counter, Production Floor, Cold Room). Generic + idempotent.
--
--  Depends on: seed_demo.sql (creates the demo tenant + Main Warehouse) and
--  import_targets_supplier_warehouse.sql (adds warehouses.warehouse_type).
-- ============================================================================
DO $$
DECLARE v_tenant UUID;
BEGIN
    SELECT id INTO v_tenant FROM tenants WHERE slug = 'demo';
    IF v_tenant IS NULL THEN
        RETURN;  -- demo tenant not seeded (e.g. production); nothing to do
    END IF;

    -- Classify the existing main warehouse.
    UPDATE warehouses
       SET warehouse_type = COALESCE(warehouse_type, 'main')
     WHERE tenant_id = v_tenant AND code = 'WH-MAIN';

    -- Add the demo internal locations (matched by code per tenant; safe to re-run).
    INSERT INTO warehouses (tenant_id, code, name, warehouse_type)
    SELECT v_tenant, x.code, x.name, x.wtype
    FROM (VALUES
        ('LOC-CASHIER',  'Cashier Room', 'counter'),
        ('LOC-WORKSHOP', 'Workshop',     'store'),
        ('LOC-SHOWROOM', 'Showroom',     'store')
    ) AS x(code, name, wtype)
    WHERE NOT EXISTS (
        SELECT 1 FROM warehouses w WHERE w.tenant_id = v_tenant AND w.code = x.code
    );
END $$;
