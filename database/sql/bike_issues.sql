-- ============================================================================
--  Bike Issues — record an INTERNAL repair on a bike we own that has a fault, and
--  consume the spare part(s) used to fix it.
--
--  This is NOT a customer sale. Customers buy parts only through POS / sales. Here a
--  bike in our own stock has a problem, and we take part(s) from our own inventory to
--  repair it. The part is CONSUMED as an internal cost — no invoice, no customer.
--
--  STOCK RULE (the important part): consuming a part goes through the ONE existing
--  inventory write path (InventoryService.issue): lock the row, check available,
--  decrement qty_on_hand, write ONE append-only stock_movements ledger entry, audit.
--  The movement is tagged reference_type='bike_repair' so reports can tell an internal
--  repair-consumption apart from a POS sale. NOTHING here writes qty_on_hand directly.
--
--  BIKE STATUS TIE-IN: opening an issue routes the unit to `on_hold` (reusing the
--  serialized lifecycle) so it can't be sold mid-repair, with the issue as the hold
--  reason; resolving returns it to its prior sellable status. Both transitions are
--  written to the unit's own event ledger.
--
--  Additive tables only; no data changed. Idempotent. Reuses next_sales_number.
-- ============================================================================

CREATE TABLE IF NOT EXISTS bike_issues (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    issue_number         TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'open'
                          CONSTRAINT bike_issues_status_ck CHECK (status IN
                            ('open','in_repair','resolved')),
    unit_id              UUID NOT NULL REFERENCES motorcycle_units(id) ON DELETE RESTRICT,
    -- Snapshot of the unit's identity at open time (read from the unit, never retyped),
    -- so a chassis's repair history is preserved even if the unit record later changes.
    chassis_number       TEXT NOT NULL,
    engine_number        TEXT,
    branch_id            UUID REFERENCES branches(id) ON DELETE SET NULL,
    -- The unit's sale status just before we put it on hold, restored on resolve.
    prior_status         TEXT NOT NULL,
    problem_description   TEXT NOT NULL,
    reported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    reported_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at          TIMESTAMPTZ,
    resolved_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    resolution_note      TEXT,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, issue_number)
);
CREATE INDEX IF NOT EXISTS idx_bike_issues_tenant_status ON bike_issues (tenant_id, status, reported_at DESC);
CREATE INDEX IF NOT EXISTS idx_bike_issues_unit ON bike_issues (unit_id);
CREATE INDEX IF NOT EXISTS idx_bike_issues_branch ON bike_issues (branch_id);

DROP TRIGGER IF EXISTS trg_bike_issues_updated_at ON bike_issues;
CREATE TRIGGER trg_bike_issues_updated_at
    BEFORE UPDATE ON bike_issues FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS bike_issue_lines (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    issue_id      UUID NOT NULL REFERENCES bike_issues(id) ON DELETE CASCADE,
    -- The fungible spare PART consumed and the source location it came from.
    product_id    UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    warehouse_id  UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    quantity      NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    -- Deduction happens at resolve; these record that it happened (traceable to the ledger).
    consumed      BOOLEAN NOT NULL DEFAULT false,
    consumed_at   TIMESTAMPTZ,
    remarks       TEXT
);
CREATE INDEX IF NOT EXISTS idx_bike_issue_lines_issue ON bike_issue_lines (issue_id);
CREATE INDEX IF NOT EXISTS idx_bike_issue_lines_product ON bike_issue_lines (product_id);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['bike_issues','bike_issue_lines']
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
    ('bike_issue.read',   'View bike repair issues and their consumed parts'),
    ('bike_issue.manage', 'Open bike repair issues, add repair parts, and resolve them (consumes stock)')
ON CONFLICT (code) DO NOTHING;

-- Admin: everything.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('bike_issue.read','bike_issue.manage')
WHERE r.is_system AND r.name = 'Admin'
ON CONFLICT DO NOTHING;

-- Branch Manager, Inventory Manager, Warehouse Manager: open + resolve repairs.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('bike_issue.read','bike_issue.manage')
WHERE r.is_system AND r.name IN ('Branch Manager','Inventory Manager','Warehouse Manager')
ON CONFLICT DO NOTHING;

-- Salesperson, Cashier, Finance, Procurement Manager, Viewer: read-only visibility.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'bike_issue.read'
WHERE r.is_system AND r.name IN ('Salesperson','Cashier','Finance','Procurement Manager','Viewer')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE bike_issues IS 'Internal bike repair issues: a fault on a bike we own; parts are consumed from our own stock (never a customer sale). Opening holds the unit; resolving consumes the parts via the single inventory write path and releases the unit.';
COMMENT ON TABLE bike_issue_lines IS 'Repair parts consumed to fix a bike issue: fungible product + source warehouse + qty; deducted through InventoryService at resolve (movement reference_type=bike_repair).';
