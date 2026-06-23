-- ============================================================================
--  OPTIONAL SAMPLE DATA — motorcycle dealership scenario (for assistant testing)
--
--  Adds, to the existing "Demo Distributors" tenant (slug=demo):
--    * 3 branches: Lusaka (LUS), Ndola (NDL), Solwezi (SOL)
--    * 4 motorcycle models + 4 spare parts (with reorder points)
--    * starting inventory across the 3 branches (several deliberately BELOW reorder)
--    * 14 days of sales INCLUDING today, so "today's sales report" returns data
--
--  Idempotent: re-running is a no-op once 'MC-HLX-150' exists. Not wired into
--  docker-compose; apply manually:
--      docker compose exec -T db psql -U postgres -d inventory -f - < database/sql/sample_motorcycle_demo.sql
--  (or pipe the file in). Safe to delete this file; it is test-only data.
-- ============================================================================
DO $$
DECLARE
    v_tenant  UUID;
    v_lusaka  UUID; v_ndola UUID; v_solwezi UUID;
    v_cat_mc  UUID; v_cat_sp UUID;
    v_br_tvs  UUID; v_br_baj UUID;
    v_sup     UUID;
    v_hlx UUID; v_rtr UUID; v_bxr UUID; v_pul UUID;
    v_plug UUID; v_brake UUID; v_chain UUID; v_filter UUID;
BEGIN
    SELECT id INTO v_tenant FROM tenants WHERE slug = 'demo';
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'demo tenant (slug=demo) not found — run seed_demo.sql first';
    END IF;
    -- Required so RLS WITH CHECK passes if this runs as the non-superuser app_user.
    PERFORM set_config('app.current_tenant', v_tenant::text, false);

    IF EXISTS (SELECT 1 FROM products WHERE tenant_id = v_tenant AND sku = 'MC-HLX-150') THEN
        RAISE NOTICE 'Motorcycle sample data already present — nothing to do.';
        RETURN;
    END IF;

    -- ---- Branches (reuse by code if they already exist) ----
    SELECT id INTO v_lusaka FROM warehouses WHERE tenant_id = v_tenant AND code = 'LUS';
    IF v_lusaka IS NULL THEN
        INSERT INTO warehouses (tenant_id, code, name, address)
        VALUES (v_tenant, 'LUS', 'Lusaka', 'Cairo Road, Lusaka') RETURNING id INTO v_lusaka;
    END IF;
    SELECT id INTO v_ndola FROM warehouses WHERE tenant_id = v_tenant AND code = 'NDL';
    IF v_ndola IS NULL THEN
        INSERT INTO warehouses (tenant_id, code, name, address)
        VALUES (v_tenant, 'NDL', 'Ndola', 'Buteko Avenue, Ndola') RETURNING id INTO v_ndola;
    END IF;
    SELECT id INTO v_solwezi FROM warehouses WHERE tenant_id = v_tenant AND code = 'SOL';
    IF v_solwezi IS NULL THEN
        INSERT INTO warehouses (tenant_id, code, name, address)
        VALUES (v_tenant, 'SOL', 'Solwezi', 'Independence Avenue, Solwezi') RETURNING id INTO v_solwezi;
    END IF;

    -- ---- Categories / brands / supplier (reuse if present) ----
    SELECT id INTO v_cat_mc FROM categories WHERE tenant_id = v_tenant AND name = 'Motorcycles';
    IF v_cat_mc IS NULL THEN INSERT INTO categories (tenant_id, name) VALUES (v_tenant, 'Motorcycles') RETURNING id INTO v_cat_mc; END IF;
    SELECT id INTO v_cat_sp FROM categories WHERE tenant_id = v_tenant AND name = 'Spare Parts';
    IF v_cat_sp IS NULL THEN INSERT INTO categories (tenant_id, name) VALUES (v_tenant, 'Spare Parts') RETURNING id INTO v_cat_sp; END IF;
    SELECT id INTO v_br_tvs FROM brands WHERE tenant_id = v_tenant AND name = 'TVS';
    IF v_br_tvs IS NULL THEN INSERT INTO brands (tenant_id, name) VALUES (v_tenant, 'TVS') RETURNING id INTO v_br_tvs; END IF;
    SELECT id INTO v_br_baj FROM brands WHERE tenant_id = v_tenant AND name = 'Bajaj';
    IF v_br_baj IS NULL THEN INSERT INTO brands (tenant_id, name) VALUES (v_tenant, 'Bajaj') RETURNING id INTO v_br_baj; END IF;
    SELECT id INTO v_sup FROM suppliers WHERE tenant_id = v_tenant AND name = 'Zambia Moto Imports';
    IF v_sup IS NULL THEN
        INSERT INTO suppliers (tenant_id, name, contact_person, email, country, currency, payment_terms, default_lead_time_days)
        VALUES (v_tenant, 'Zambia Moto Imports', 'K. Mwale', 'sales@zammoto.test', 'ZM', 'USD', 'Net 30', 30)
        RETURNING id INTO v_sup;
    END IF;

    -- ---- Products: 4 motorcycles + 4 spare parts, with reorder points ----
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'MC-HLX-150', 'TVS HLX 150 Motorcycle', v_cat_mc, v_br_tvs, v_sup,  950, 1300, 1, 5, 30, 5) RETURNING id INTO v_hlx;
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'MC-RTR-200', 'TVS Apache RTR 200', v_cat_mc, v_br_tvs, v_sup, 1450, 1950, 1, 4, 30, 4) RETURNING id INTO v_rtr;
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'MC-BXR-150', 'Bajaj Boxer 150', v_cat_mc, v_br_baj, v_sup, 1100, 1500, 1, 6, 30, 6) RETURNING id INTO v_bxr;
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'MC-PUL-180', 'Bajaj Pulsar 180', v_cat_mc, v_br_baj, v_sup, 1300, 1750, 1, 4, 30, 4) RETURNING id INTO v_pul;

    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'SP-PLUG-HLX', 'Spark Plug - HLX 150', v_cat_sp, v_br_tvs, v_sup, 3.0, 7.0, 50, 100, 21, 50) RETURNING id INTO v_plug;
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'SP-BRAKE-PAD', 'Brake Pad Set - Universal', v_cat_sp, v_br_baj, v_sup, 9.0, 19.0, 20, 60, 21, 40) RETURNING id INTO v_brake;
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'SP-CHAIN-428', 'Drive Chain 428H', v_cat_sp, v_br_tvs, v_sup, 13.0, 27.0, 25, 50, 21, 30) RETURNING id INTO v_chain;
    INSERT INTO products (tenant_id, sku, name, category_id, brand_id, primary_supplier_id,
        cost_price, selling_price, units_per_carton, moq, lead_time_days, reorder_point) VALUES
        (v_tenant, 'SP-AIRFILT', 'Air Filter - HLX/Apache', v_cat_sp, v_br_tvs, v_sup, 4.0, 9.0, 40, 80, 21, 60) RETURNING id INTO v_filter;

    -- ---- Inventory across the 3 branches (rows marked LOW are below reorder) ----
    INSERT INTO inventory (tenant_id, product_id, warehouse_id, qty_on_hand, qty_reserved, qty_damaged) VALUES
        (v_tenant, v_hlx,    v_lusaka, 12, 0, 0), (v_tenant, v_hlx,    v_ndola,  7, 0, 0), (v_tenant, v_hlx,    v_solwezi, 3, 0, 0),  -- Solwezi LOW (<5)
        (v_tenant, v_rtr,    v_lusaka,  6, 0, 0), (v_tenant, v_rtr,    v_ndola,  2, 0, 0), (v_tenant, v_rtr,    v_solwezi, 0, 0, 0),  -- Ndola LOW, Solwezi OUT
        (v_tenant, v_bxr,    v_lusaka,  9, 0, 0), (v_tenant, v_bxr,    v_ndola,  8, 0, 0), (v_tenant, v_bxr,    v_solwezi, 5, 0, 0),  -- Solwezi LOW (<6)
        (v_tenant, v_pul,    v_lusaka,  5, 0, 0), (v_tenant, v_pul,    v_ndola,  4, 0, 0), (v_tenant, v_pul,    v_solwezi, 6, 0, 0),
        (v_tenant, v_plug,   v_lusaka,200, 0, 0), (v_tenant, v_plug,   v_ndola, 30, 0, 0), (v_tenant, v_plug,   v_solwezi,80, 0, 0),  -- Ndola LOW (<50)
        (v_tenant, v_brake,  v_lusaka, 35, 0, 0), (v_tenant, v_brake,  v_ndola, 60, 0, 0), (v_tenant, v_brake,  v_solwezi,50, 0, 0),  -- Lusaka LOW (<40)
        (v_tenant, v_chain,  v_lusaka, 25, 0, 0), (v_tenant, v_chain,  v_ndola, 40, 0, 0), (v_tenant, v_chain,  v_solwezi,35, 0, 0),  -- Lusaka LOW (<30)
        (v_tenant, v_filter, v_lusaka,100, 0, 0), (v_tenant, v_filter, v_ndola, 70, 0, 0), (v_tenant, v_filter, v_solwezi,45, 0, 0);  -- Solwezi LOW (<60)

    -- ---- Sales: last 13 days (random) + a deterministic TODAY so reports are non-empty ----
    INSERT INTO sales_daily (tenant_id, product_id, warehouse_id, sale_date, qty_sold)
    SELECT v_tenant, p.pid, w.wid, g::date,
           GREATEST(0, round(random() * CASE WHEN p.is_mc THEN 1.5 ELSE 6 END))::numeric
    FROM (VALUES (v_hlx, true), (v_rtr, true), (v_bxr, true), (v_pul, true),
                 (v_plug, false), (v_brake, false), (v_chain, false), (v_filter, false)) AS p(pid, is_mc)
    CROSS JOIN (VALUES (v_lusaka), (v_ndola), (v_solwezi)) AS w(wid)
    CROSS JOIN generate_series(current_date - 13, current_date - 1, interval '1 day') AS s(g);

    INSERT INTO sales_daily (tenant_id, product_id, warehouse_id, sale_date, qty_sold) VALUES
        (v_tenant, v_hlx,   v_lusaka, current_date, 2),
        (v_tenant, v_hlx,   v_ndola,  current_date, 1),
        (v_tenant, v_rtr,   v_lusaka, current_date, 1),
        (v_tenant, v_bxr,   v_solwezi,current_date, 1),
        (v_tenant, v_plug,  v_lusaka, current_date, 6),
        (v_tenant, v_brake, v_ndola,  current_date, 4),
        (v_tenant, v_chain, v_lusaka, current_date, 3),
        (v_tenant, v_filter,v_solwezi,current_date, 5);

    RAISE NOTICE 'Motorcycle sample data added to tenant % (branches Lusaka/Ndola/Solwezi).', v_tenant;
END;
$$;

-- Configure the DEMO tenant's business identity (TVS Zambia). The core platform is
-- generic; this is just tenant configuration, so the same engine serves any industry.
-- Idempotent. (Note: demo prices are illustrative, not real ZMW values.)
UPDATE tenants SET
    brand_name       = 'TVS',
    industry         = 'Motorcycles and Spare Parts',
    country          = 'Zambia',
    timezone         = 'Africa/Lusaka',
    assistant_name   = 'TVS Zambia Assistant',
    assistant_prompt = 'You assist managers and branch staff at a motorcycle and spare-parts '
                       'dealership. Be concise and practical; prefer per-branch breakdowns.',
    base_currency    = 'ZMW'
WHERE slug = 'demo';

-- Demo users for role-based testing (idempotent). Both scoped to the Lusaka branch via
-- user_warehouse_access, so they see only that branch. Login password: ChangeMe123!
--   cashier@demo.com  (Cashier)        -> read-only inventory + create/track order requests
--   manager@demo.com  (Branch Manager) -> approve/reject/issue requests for the branch
DO $$
DECLARE
    v_tenant UUID; v_lusaka UUID; v_uid UUID;
    v_role_cashier UUID; v_role_bm UUID;
BEGIN
    SELECT id INTO v_tenant FROM tenants WHERE slug = 'demo';
    IF v_tenant IS NULL THEN RETURN; END IF;
    PERFORM set_config('app.current_tenant', v_tenant::text, false);
    SELECT id INTO v_lusaka FROM warehouses WHERE tenant_id = v_tenant AND code = 'LUS';
    SELECT id INTO v_role_cashier FROM roles WHERE is_system AND name = 'Cashier';
    SELECT id INTO v_role_bm FROM roles WHERE is_system AND name = 'Branch Manager';

    -- Cashier
    SELECT id INTO v_uid FROM users WHERE tenant_id = v_tenant AND email = 'cashier@demo.com';
    IF v_uid IS NULL THEN
        INSERT INTO users (tenant_id, email, password_hash, full_name)
        VALUES (v_tenant, 'cashier@demo.com', crypt('ChangeMe123!', gen_salt('bf', 12)), 'Demo Cashier')
        RETURNING id INTO v_uid;
    END IF;
    IF v_role_cashier IS NOT NULL THEN
        INSERT INTO user_roles (user_id, role_id) VALUES (v_uid, v_role_cashier) ON CONFLICT DO NOTHING;
    END IF;
    IF v_lusaka IS NOT NULL THEN
        INSERT INTO user_warehouse_access (tenant_id, user_id, warehouse_id)
        VALUES (v_tenant, v_uid, v_lusaka) ON CONFLICT DO NOTHING;
    END IF;

    -- Branch Manager
    SELECT id INTO v_uid FROM users WHERE tenant_id = v_tenant AND email = 'manager@demo.com';
    IF v_uid IS NULL THEN
        INSERT INTO users (tenant_id, email, password_hash, full_name)
        VALUES (v_tenant, 'manager@demo.com', crypt('ChangeMe123!', gen_salt('bf', 12)), 'Demo Branch Manager')
        RETURNING id INTO v_uid;
    END IF;
    IF v_role_bm IS NOT NULL THEN
        INSERT INTO user_roles (user_id, role_id) VALUES (v_uid, v_role_bm) ON CONFLICT DO NOTHING;
    END IF;
    IF v_lusaka IS NOT NULL THEN
        INSERT INTO user_warehouse_access (tenant_id, user_id, warehouse_id)
        VALUES (v_tenant, v_uid, v_lusaka) ON CONFLICT DO NOTHING;
    END IF;

    RAISE NOTICE 'Demo role users ready: cashier@demo.com / manager@demo.com (ChangeMe123!), scoped to Lusaka.';
END $$;

