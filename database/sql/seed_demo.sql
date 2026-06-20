-- ============================================================================
--  DEMO SEED  (OPTIONAL — development / evaluation only, generic data)
--
--  Creates TWO tenants so multi-tenant isolation is demonstrable/testable:
--    * "Demo Distributors" (slug demo)   — the rich primary tenant: two
--      warehouses, a generic multi-industry catalog, starting inventory (incl.
--      one out-of-stock and a couple of low-stock items), and ~90 days of sales
--      history so the reorder engine has real data to work with.
--    * "Globex Industrial" (slug globex) — a minimal second tenant used to prove
--      PostgreSQL Row-Level Security keeps tenants' data fully separated.
--
--  Run after schema.sql + seed_rbac.sql:
--      psql "$DATABASE_URL" -f sql/seed_demo.sql
--
--  Demo logins ->  admin@demo.com / ChangeMe123!   and   admin@globex.com / ChangeMe123!
--  (Real bcrypt hashes generated via pgcrypto crypt()/gen_salt('bf').)
--  Do NOT load this into a production database.
-- ============================================================================

DO $$
DECLARE
    v_tenant     UUID;
    v_admin_role UUID;
    v_user       UUID;
    v_wh_main    UUID;
    v_wh_2       UUID;
    v_cat_el     UUID;
    v_cat_hw     UUID;
    v_cat_ac     UUID;
    v_br_gen     UUID;
    v_br_acme    UUID;
    v_sup_acme   UUID;
    v_sup_fe     UUID;
    v_cable      UUID;
    v_charger    UUID;
    v_drill      UUID;
    v_screw      UUID;
    v_mug        UUID;
    v_bottle     UUID;
BEGIN
    -- Tenant (no RLS on tenants)
    INSERT INTO tenants (name, slug, base_currency, fx_rate, vat_rate)
    VALUES ('Demo Distributors', 'demo', 'USD', 1.000000, 0.1600)
    RETURNING id INTO v_tenant;

    -- Required so every subsequent RLS-protected INSERT passes WITH CHECK.
    PERFORM set_config('app.current_tenant', v_tenant::text, false);

    -- Admin user with a real, verifiable bcrypt hash
    INSERT INTO users (tenant_id, email, password_hash, full_name)
    VALUES (v_tenant, 'admin@demo.com', crypt('ChangeMe123!', gen_salt('bf', 12)), 'Demo Admin')
    RETURNING id INTO v_user;

    -- Grant the global Admin system role
    SELECT id INTO v_admin_role FROM roles WHERE is_system AND name = 'Admin';
    IF v_admin_role IS NOT NULL THEN
        INSERT INTO user_roles (user_id, role_id) VALUES (v_user, v_admin_role)
        ON CONFLICT DO NOTHING;
    END IF;

    -- Warehouses
    INSERT INTO warehouses (tenant_id, code, name, address)
    VALUES (v_tenant, 'WH-MAIN', 'Main Warehouse', '1 Industrial Rd') RETURNING id INTO v_wh_main;
    INSERT INTO warehouses (tenant_id, code, name, address)
    VALUES (v_tenant, 'WH-2', 'Secondary Warehouse', '14 Depot Ave')  RETURNING id INTO v_wh_2;

    -- Categories
    INSERT INTO categories (tenant_id, name) VALUES (v_tenant, 'Electronics')  RETURNING id INTO v_cat_el;
    INSERT INTO categories (tenant_id, name) VALUES (v_tenant, 'Hardware')     RETURNING id INTO v_cat_hw;
    INSERT INTO categories (tenant_id, name) VALUES (v_tenant, 'Accessories')  RETURNING id INTO v_cat_ac;

    -- Brands
    INSERT INTO brands (tenant_id, name) VALUES (v_tenant, 'GenericCo') RETURNING id INTO v_br_gen;
    INSERT INTO brands (tenant_id, name) VALUES (v_tenant, 'Acme')      RETURNING id INTO v_br_acme;

    -- Suppliers
    INSERT INTO suppliers (tenant_id, name, contact_person, email, country, currency, payment_terms, default_lead_time_days)
    VALUES (v_tenant, 'Acme Trading Co', 'J. Rivera', 'sales@acmetrading.test', 'USA', 'USD', 'Net 30', 45)
    RETURNING id INTO v_sup_acme;
    INSERT INTO suppliers (tenant_id, name, contact_person, email, country, currency, payment_terms, default_lead_time_days)
    VALUES (v_tenant, 'Far East Imports', 'L. Chen', 'orders@fareast.test', 'CN', 'USD', '30% deposit', 60)
    RETURNING id INTO v_sup_fe;

    -- Products (generic, varied pack sizes / MOQ / lead time; some pallet+container dims)
    INSERT INTO products (tenant_id, sku, barcode, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days,
        weight_per_unit, volume_per_unit, weight_per_carton, volume_per_carton, cartons_per_pallet)
    VALUES (v_tenant, 'EL-CABLE-USB-C-1M', '8900000000017', 'USB-C Cable 1m', v_cat_el, v_br_gen, v_sup_acme,
        1.2000, 3.5000, 50, 500, 45, 0.05, 0.0002, 2.6, 0.011, 96)
    RETURNING id INTO v_cable;

    INSERT INTO products (tenant_id, sku, barcode, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days)
    VALUES (v_tenant, 'EL-CHARGER-20W', '8900000000024', '20W USB-C Charger', v_cat_el, v_br_gen, v_sup_acme,
        4.5000, 11.0000, 20, 200, 45)
    RETURNING id INTO v_charger;

    INSERT INTO products (tenant_id, sku, barcode, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days,
        weight_per_unit, weight_per_carton, cartons_per_pallet)
    VALUES (v_tenant, 'HW-DRILL-18V', '8900000000031', '18V Cordless Drill', v_cat_hw, v_br_acme, v_sup_fe,
        28.0000, 59.0000, 6, 24, 60, 1.8, 11.2, 40)
    RETURNING id INTO v_drill;

    INSERT INTO products (tenant_id, sku, barcode, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days)
    VALUES (v_tenant, 'HW-SCREW-M4-100', '8900000000048', 'M4 Screws (pack of 100)', v_cat_hw, v_br_gen, v_sup_fe,
        0.8000, 2.2000, 100, 1000, 30)
    RETURNING id INTO v_screw;

    INSERT INTO products (tenant_id, sku, barcode, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days)
    VALUES (v_tenant, 'AC-MUG-350', '8900000000055', 'Ceramic Mug 350ml', v_cat_ac, v_br_gen, v_sup_acme,
        1.5000, 4.5000, 36, 360, 45)
    RETURNING id INTO v_mug;

    INSERT INTO products (tenant_id, sku, barcode, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days)
    VALUES (v_tenant, 'AC-BOTTLE-750', '8900000000062', 'Steel Water Bottle 750ml', v_cat_ac, v_br_acme, v_sup_fe,
        3.2000, 9.0000, 24, 240, 60)
    RETURNING id INTO v_bottle;

    -- Supplier-product terms (primary), plus a second source for the cable (multi-sourcing demo)
    INSERT INTO supplier_products (tenant_id, supplier_id, product_id, cost_price, currency, moq, lead_time_days, units_per_carton, is_preferred) VALUES
        (v_tenant, v_sup_acme, v_cable,   1.2000, 'USD', 500,  45, 50,  TRUE),
        (v_tenant, v_sup_fe,   v_cable,   1.0500, 'USD', 1000, 60, 50,  FALSE),
        (v_tenant, v_sup_acme, v_charger, 4.5000, 'USD', 200,  45, 20,  TRUE),
        (v_tenant, v_sup_fe,   v_drill,  28.0000, 'USD', 24,   60, 6,   TRUE),
        (v_tenant, v_sup_fe,   v_screw,   0.8000, 'USD', 1000, 30, 100, TRUE),
        (v_tenant, v_sup_acme, v_mug,     1.5000, 'USD', 360,  45, 36,  TRUE),
        (v_tenant, v_sup_fe,   v_bottle,  3.2000, 'USD', 240,  60, 24,  TRUE);

    -- Starting inventory (one out-of-stock, two low, others healthy)
    INSERT INTO inventory (tenant_id, product_id, warehouse_id, qty_on_hand, qty_reserved, qty_damaged) VALUES
        (v_tenant, v_cable,   v_wh_main, 120, 0,  0),
        (v_tenant, v_charger, v_wh_main, 0,   0,  0),   -- out of stock
        (v_tenant, v_drill,   v_wh_main, 40,  4,  0),
        (v_tenant, v_screw,   v_wh_main, 5000,0,  0),
        (v_tenant, v_mug,     v_wh_main, 80,  0,  6),    -- some damaged
        (v_tenant, v_bottle,  v_wh_main, 300, 0,  0),
        (v_tenant, v_cable,   v_wh_2,    200, 0,  0),
        (v_tenant, v_drill,   v_wh_2,    10,  0,  0);

    -- ~90 days of daily sales (Main warehouse) for fast movers, so the engine triggers
    INSERT INTO sales_daily (tenant_id, product_id, warehouse_id, sale_date, qty_sold)
    SELECT v_tenant, v_cable, v_wh_main, g::date, GREATEST(0, round(random()*10 + 4))::numeric
    FROM generate_series(current_date - 89, current_date, interval '1 day') AS s(g);

    INSERT INTO sales_daily (tenant_id, product_id, warehouse_id, sale_date, qty_sold)
    SELECT v_tenant, v_charger, v_wh_main, g::date, GREATEST(0, round(random()*6 + 3))::numeric
    FROM generate_series(current_date - 89, current_date, interval '1 day') AS s(g);

    INSERT INTO sales_daily (tenant_id, product_id, warehouse_id, sale_date, qty_sold)
    SELECT v_tenant, v_mug, v_wh_main, g::date, GREATEST(0, round(random()*5 + 2))::numeric
    FROM generate_series(current_date - 89, current_date, interval '1 day') AS s(g);

    INSERT INTO sales_daily (tenant_id, product_id, warehouse_id, sale_date, qty_sold)
    SELECT v_tenant, v_drill, v_wh_main, g::date, GREATEST(0, round(random()*1.5))::numeric
    FROM generate_series(current_date - 89, current_date, interval '1 day') AS s(g);

    RAISE NOTICE 'Demo tenant created: % (slug=demo, login admin@demo.com / ChangeMe123!)', v_tenant;
END;
$$;

-- ----------------------------------------------------------------------------
--  Second tenant — minimal footprint, used to prove cross-tenant RLS isolation.
--  Login ->  email: admin@globex.com   password: ChangeMe123!
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_tenant     UUID;
    v_admin_role UUID;
    v_user       UUID;
    v_wh         UUID;
    v_widget     UUID;
BEGIN
    INSERT INTO tenants (name, slug, base_currency, fx_rate, vat_rate)
    VALUES ('Globex Industrial', 'globex', 'USD', 1.000000, 0.0000)
    RETURNING id INTO v_tenant;

    -- Scope the subsequent RLS-protected INSERTs to this tenant.
    PERFORM set_config('app.current_tenant', v_tenant::text, false);

    INSERT INTO users (tenant_id, email, password_hash, full_name)
    VALUES (v_tenant, 'admin@globex.com', crypt('ChangeMe123!', gen_salt('bf', 12)), 'Globex Admin')
    RETURNING id INTO v_user;

    SELECT id INTO v_admin_role FROM roles WHERE is_system AND name = 'Admin';
    IF v_admin_role IS NOT NULL THEN
        INSERT INTO user_roles (user_id, role_id) VALUES (v_user, v_admin_role)
        ON CONFLICT DO NOTHING;
    END IF;

    INSERT INTO warehouses (tenant_id, code, name, address)
    VALUES (v_tenant, 'GX-WH', 'Globex Warehouse', '500 Globex Plaza') RETURNING id INTO v_wh;

    -- A single product whose SKU exists ONLY in this tenant.
    INSERT INTO products (tenant_id, sku, name, cost_price, selling_price, units_per_carton, moq, lead_time_days)
    VALUES (v_tenant, 'GX-WIDGET-001', 'Globex Widget', 5.0000, 12.0000, 10, 100, 30)
    RETURNING id INTO v_widget;

    INSERT INTO inventory (tenant_id, product_id, warehouse_id, qty_on_hand, qty_reserved, qty_damaged)
    VALUES (v_tenant, v_widget, v_wh, 250, 0, 0);

    RAISE NOTICE 'Second tenant created: % (slug=globex, login admin@globex.com / ChangeMe123!)', v_tenant;
END;
$$;
