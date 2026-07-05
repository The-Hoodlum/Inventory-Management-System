-- ============================================================================
--  Branch -> Customer / Reseller delivery — Type 3 of the delivery-note area.
--
--  Two modes (a per-delivery flag), both PAPER that documents a movement — never a
--  second stock-write path:
--    * sale         : generated FROM a sale/invoice. Lists the sold bikes (by chassis)
--                     + parts and records the handover. Reflects the deduction the sale
--                     ALREADY made — does NOT deduct again.
--    * consignment  : goods sit at the reseller but remain OUR stock. On dispatch the
--                     parts are HELD (reservation) and the bikes CONSIGNED (out, not
--                     sellable, not deducted). As the reseller reports sales they are
--                     SETTLED (a real deduction / bike sale); unsold stock is RETURNED
--                     (holds released).
--  All stock movement goes through InventoryService + the reservation repo + the
--  serialized registry. Idempotent. Reuses next_sales_number('customer_delivery').
-- ============================================================================

CREATE TABLE IF NOT EXISTS customer_deliveries (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id)     ON DELETE CASCADE,
    delivery_number  TEXT NOT NULL,
    delivery_mode    TEXT NOT NULL CONSTRAINT customer_deliveries_mode_ck CHECK (delivery_mode IN ('sale','consignment')),
    status           TEXT NOT NULL DEFAULT 'draft'
                       CONSTRAINT customer_deliveries_status_ck CHECK (status IN
                         ('draft','delivered','out_at_reseller','partially_settled','settled','returned','cancelled')),
    branch_id        UUID REFERENCES branches(id)   ON DELETE SET NULL,
    from_warehouse_id UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    customer_id      UUID NOT NULL REFERENCES customers(id)  ON DELETE RESTRICT,
    invoice_id       UUID REFERENCES invoices(id)   ON DELETE SET NULL,   -- sale mode source
    remarks          TEXT,
    dispatched_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    dispatched_at    TIMESTAMPTZ,
    received_by      TEXT,
    received_at      TIMESTAMPTZ,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, delivery_number)
);
CREATE INDEX IF NOT EXISTS idx_customer_deliveries_tenant_status ON customer_deliveries (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_customer_deliveries_customer ON customer_deliveries (customer_id);

DROP TRIGGER IF EXISTS trg_customer_deliveries_updated_at ON customer_deliveries;
CREATE TRIGGER trg_customer_deliveries_updated_at
    BEFORE UPDATE ON customer_deliveries FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS customer_delivery_lines (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)             ON DELETE CASCADE,
    delivery_id    UUID NOT NULL REFERENCES customer_deliveries(id) ON DELETE CASCADE,
    line_kind      TEXT NOT NULL CHECK (line_kind IN ('motorcycle','part')),
    product_id     UUID REFERENCES products(id) ON DELETE RESTRICT,
    unit_id        UUID REFERENCES motorcycle_units(id) ON DELETE RESTRICT,
    chassis_number TEXT,
    engine_number  TEXT,
    qty            NUMERIC(18,4) NOT NULL DEFAULT 1,   -- bikes always 1
    settled_qty    NUMERIC(18,4) NOT NULL DEFAULT 0,   -- consignment: qty converted to a sale
    returned_qty   NUMERIC(18,4) NOT NULL DEFAULT 0,   -- consignment: unsold returned
    sold_invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,  -- consignment bike settled
    remarks        TEXT,
    CHECK ((line_kind = 'part' AND product_id IS NOT NULL)
        OR (line_kind = 'motorcycle' AND unit_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_customer_delivery_lines_delivery ON customer_delivery_lines (delivery_id);
CREATE INDEX IF NOT EXISTS idx_customer_delivery_lines_unit ON customer_delivery_lines (unit_id);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['customer_deliveries','customer_delivery_lines']
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

COMMENT ON TABLE customer_deliveries IS 'Branch -> customer/reseller delivery notes: sale (proof of a sale''s handover, no re-deduct) or consignment (stock held at reseller, settled as sold).';
COMMENT ON TABLE customer_delivery_lines IS 'Customer-delivery lines: a bike by chassis or a fungible product; consignment tracks settled (sold) vs returned (unsold).';
