-- ============================================================================
--  Internal Issuance / Handover (out-and-back loan) — Type 4 of the delivery-note
--  feature area. Issue a bike and/or items to a department/person for an event,
--  test, display, etc., then get them back.
--
--  STOCK RULE (the important part): an issuance NEVER sells and NEVER permanently
--  deducts RETURNABLE stock — it makes the issued thing temporarily NOT sellable
--  while it is out, then returns it:
--    * serialized bikes: an OPEN issuance line marks the unit out-on-loan (derived
--      into availability; NOT a 6th sale-status, NOT `on_hold`). On clean return the
--      unit is available again; a "needs attention" (damaged) return routes it to
--      `on_hold` with the return note as the hold reason.
--    * fungible items: the issued qty is HELD (qty_reserved up; qty_on_hand unchanged)
--      via the reservation mechanism, so AVAILABLE drops. Return releases it.
--    * consumable / non-returnable lines: deducted for real at handover (issue), not
--      expected back.
--  No stock is written here — the service drives InventoryService + the reservation
--  repository + the serialized registry. Idempotent. Reuses next_sales_number('issuance').
-- ============================================================================

CREATE TABLE IF NOT EXISTS issuances (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id)     ON DELETE CASCADE,
    issuance_number      TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'draft'
                          CONSTRAINT issuances_status_ck CHECK (status IN
                            ('draft','out_on_loan','partially_returned','returned','cancelled')),
    branch_id            UUID REFERENCES branches(id)   ON DELETE SET NULL,
    warehouse_id         UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    -- Handover header (from the "Handover Form"): who/where/why + when it's due back.
    requestor            TEXT,
    department           TEXT,
    purpose              TEXT,     -- event / activity / reason
    expected_return_date DATE,
    remarks              TEXT,
    issued_by            UUID REFERENCES users(id) ON DELETE SET NULL,
    issued_at            TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    created_by           UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, issuance_number)
);
CREATE INDEX IF NOT EXISTS idx_issuances_tenant_status ON issuances (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_issuances_branch ON issuances (branch_id);

DROP TRIGGER IF EXISTS trg_issuances_updated_at ON issuances;
CREATE TRIGGER trg_issuances_updated_at
    BEFORE UPDATE ON issuances FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS issuance_lines (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id)     ON DELETE CASCADE,
    issuance_id   UUID NOT NULL REFERENCES issuances(id)   ON DELETE CASCADE,
    line_kind     TEXT NOT NULL CHECK (line_kind IN ('motorcycle','part')),
    product_id    UUID REFERENCES products(id) ON DELETE RESTRICT,
    unit_id       UUID REFERENCES motorcycle_units(id) ON DELETE RESTRICT,
    chassis_number TEXT,
    engine_number  TEXT,
    qty           NUMERIC(18,4) NOT NULL DEFAULT 1,   -- bikes always 1
    returnable    BOOLEAN NOT NULL DEFAULT true,
    consumable    BOOLEAN NOT NULL DEFAULT false,     -- non-returnable item: deducted at handover
    -- Handover details (bikes) + return leg.
    odometer_out  NUMERIC(18,2),
    fuel_out      TEXT,
    accessories   TEXT,
    returned_qty  NUMERIC(18,4) NOT NULL DEFAULT 0,
    missing_qty   NUMERIC(18,4) NOT NULL DEFAULT 0,
    condition     TEXT,     -- bike return: good | fair | needs_attention
    odometer_in   NUMERIC(18,2),
    return_note   TEXT,
    returned_at   TIMESTAMPTZ,
    remarks       TEXT,
    CHECK ((line_kind = 'part' AND product_id IS NOT NULL)
        OR (line_kind = 'motorcycle' AND unit_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_issuance_lines_issuance ON issuance_lines (issuance_id);
CREATE INDEX IF NOT EXISTS idx_issuance_lines_unit ON issuance_lines (unit_id);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['issuances','issuance_lines']
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

COMMENT ON TABLE issuances IS 'Internal issuance / handover (out-and-back loan): temporarily makes stock not-sellable without a permanent deduction; documents the return leg.';
COMMENT ON TABLE issuance_lines IS 'Issuance lines: a bike (out-on-loan by chassis) or a fungible item (held qty); consumable lines are deducted at handover.';
