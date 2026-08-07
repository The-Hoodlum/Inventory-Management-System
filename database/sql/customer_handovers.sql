-- ============================================================================
--  Customer Handover — the signed record that a customer physically RECEIVED
--  their motorcycle. Based on the paper form (Customer Copy + Internal Copy).
--
--  This is NOT a stock document and never touches inventory: the sale already
--  deducted the bike. A handover is the quality / training / warranty ceremony:
--    * created against an existing invoice + serialized unit (data pulled from
--      those records, never re-typed);
--    * ONE handover per unit (unique on unit_id);
--    * completing it advances the unit as an INDEPENDENT lifecycle fact
--      (motorcycle_units.delivered + delivered_at + a 'delivered' unit event)
--      and stamps the warranty start — it does NOT change the sale status
--      (SOLD stays terminal, so sales reporting is unaffected).
--
--  Numbering reuses next_sales_number('handover','HO') -> HO-YYYY-NNNNN
--  (per-tenant/-year, consistent with every other printed document).
--  Additive tables only; idempotent.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Unit "delivered" fact (independent of the sale-status state machine, like
-- inspected / registered). Added here so both bootstrap routes converge:
-- fresh installs apply motorcycle_units.sql first, this file second; existing
-- databases pick the columns up when this module is (re)applied.
-- ---------------------------------------------------------------------------
ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS delivered    BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- Handover header (all the paper form's sections on one row — it is a single
-- signed document, not a multi-line record).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_handovers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    handover_no      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'DRAFT'
                       CONSTRAINT customer_handovers_status_ck CHECK (status IN ('DRAFT','COMPLETED')),

    -- Source documents (data is pulled FROM these; never re-typed).
    invoice_id       UUID REFERENCES invoices(id)         ON DELETE SET NULL,
    sales_order_id   UUID REFERENCES sales_orders(id)     ON DELETE SET NULL,
    unit_id          UUID NOT NULL REFERENCES motorcycle_units(id) ON DELETE RESTRICT,
    branch_id        UUID REFERENCES branches(id)         ON DELETE SET NULL,
    salesperson_id   UUID REFERENCES users(id)            ON DELETE SET NULL,

    -- Handover facts.
    delivery_date         DATE,
    warranty_start_date   DATE,
    odometer_reading_km   NUMERIC(12,2),
    fuel_level_at_delivery TEXT
                       CONSTRAINT customer_handovers_fuel_ck CHECK
                       (fuel_level_at_delivery IS NULL OR fuel_level_at_delivery IN ('E','1','2','3','4','F')),

    -- Customer snapshot (frozen at handover time; later edits to the customer
    -- master must NOT change this signed record).
    full_name         TEXT,
    nrc_passport_no   TEXT,
    phone             TEXT,
    whatsapp          TEXT,
    email             TEXT,
    physical_address  TEXT,

    -- Pre-delivery inspection checklist (workshop / mechanic).
    motorcycle_washed          BOOLEAN NOT NULL DEFAULT false,
    battery_connected          BOOLEAN NOT NULL DEFAULT false,
    engine_tested              BOOLEAN NOT NULL DEFAULT false,
    brakes_tested              BOOLEAN NOT NULL DEFAULT false,
    lights_working             BOOLEAN NOT NULL DEFAULT false,
    indicators_working         BOOLEAN NOT NULL DEFAULT false,
    horn_working               BOOLEAN NOT NULL DEFAULT false,
    mirrors_fitted             BOOLEAN NOT NULL DEFAULT false,
    tyre_pressure_checked      BOOLEAN NOT NULL DEFAULT false,
    chain_adjusted             BOOLEAN NOT NULL DEFAULT false,
    oil_level_checked          BOOLEAN NOT NULL DEFAULT false,
    throttle_operation_checked BOOLEAN NOT NULL DEFAULT false,
    toolkit_supplied           BOOLEAN NOT NULL DEFAULT false,
    owners_manual_supplied     BOOLEAN NOT NULL DEFAULT false,
    warranty_book_supplied     BOOLEAN NOT NULL DEFAULT false,
    spare_key_supplied         BOOLEAN NOT NULL DEFAULT false,
    checklist_remarks          TEXT,

    -- Customer training (handover briefing).
    controls_explained          BOOLEAN NOT NULL DEFAULT false,
    break_in_period_explained   BOOLEAN NOT NULL DEFAULT false,
    service_schedule_explained  BOOLEAN NOT NULL DEFAULT false,
    warranty_terms_explained    BOOLEAN NOT NULL DEFAULT false,
    safe_riding_explained       BOOLEAN NOT NULL DEFAULT false,
    maintenance_tips_explained  BOOLEAN NOT NULL DEFAULT false,
    training_remarks            TEXT,

    -- Items / accessories delivered.
    helmet            BOOLEAN NOT NULL DEFAULT false,
    reflector_jacket  BOOLEAN NOT NULL DEFAULT false,
    spare_key         BOOLEAN NOT NULL DEFAULT false,
    other_items       TEXT,

    -- Payment (reference from the invoice; overridable on the form).
    payment_method     TEXT
                       CONSTRAINT customer_handovers_paymethod_ck CHECK
                       (payment_method IS NULL OR payment_method IN ('Cash','Bank Transfer','Airtel Money','Other')),
    amount_paid_zmw    NUMERIC(18,4) NOT NULL DEFAULT 0,
    balance_zmw        NUMERIC(18,4) NOT NULL DEFAULT 0,
    invoice_amount_zmw NUMERIC(18,4) NOT NULL DEFAULT 0,
    internal_remarks   TEXT,

    -- Verification & approval grid (5 roles; each: name / signed / signed_at).
    mechanic_inspector_name        TEXT,
    mechanic_inspector_signed      BOOLEAN NOT NULL DEFAULT false,
    mechanic_inspector_signed_at   TIMESTAMPTZ,
    assembly_technician_name       TEXT,
    assembly_technician_signed     BOOLEAN NOT NULL DEFAULT false,
    assembly_technician_signed_at  TIMESTAMPTZ,
    quality_control_officer_name       TEXT,
    quality_control_officer_signed     BOOLEAN NOT NULL DEFAULT false,
    quality_control_officer_signed_at  TIMESTAMPTZ,
    salesperson_name               TEXT,
    salesperson_signed             BOOLEAN NOT NULL DEFAULT false,
    salesperson_signed_at          TIMESTAMPTZ,
    branch_manager_name            TEXT,
    branch_manager_signed          BOOLEAN NOT NULL DEFAULT false,
    branch_manager_signed_at       TIMESTAMPTZ,

    -- Signatures (name + date always; image is optional — base64 / file ref). The
    -- salesperson's signature time is the approval-grid salesperson_signed_at above
    -- (same signing act) — not duplicated here.
    customer_signature_name     TEXT,
    customer_signed_at          TIMESTAMPTZ,
    customer_signature_image    TEXT,
    salesperson_signature_name  TEXT,
    salesperson_signature_image TEXT,

    completed_at     TIMESTAMPTZ,
    completed_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, handover_no),
    -- One handover per physical unit (enforces "one handover per chassis/VIN").
    CONSTRAINT customer_handovers_unit_uq UNIQUE (tenant_id, unit_id)
);
CREATE INDEX IF NOT EXISTS idx_customer_handovers_tenant_status ON customer_handovers (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_customer_handovers_branch ON customer_handovers (branch_id);
CREATE INDEX IF NOT EXISTS idx_customer_handovers_invoice ON customer_handovers (invoice_id);

DROP TRIGGER IF EXISTS trg_customer_handovers_updated_at ON customer_handovers;
CREATE TRIGGER trg_customer_handovers_updated_at
    BEFORE UPDATE ON customer_handovers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (tenant isolation, identical to the other modules).
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['customer_handovers']
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

COMMENT ON TABLE customer_handovers IS 'Signed customer-handover record for a serialized motorcycle (Customer Copy + Internal Copy): pre-delivery checklist, training, accessories, payment, 5-role QC approval, signatures. One per unit; completing it marks the unit delivered + stamps warranty.';
