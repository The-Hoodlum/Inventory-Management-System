-- ============================================================================
--  Delivery / dispatch notes (typed) — PAPER that documents a stock movement.
--
--  A dispatch note NEVER mutates stock itself: the movement goes through the
--  existing InventoryService (parts) and the serialized motorcycle registry
--  (bikes). The TYPE fixes the movement + its direction — there is no add/deduct
--  toggle. One note may carry MIXED lines: motorcycle lines (a specific unit by
--  chassis) and spare-part lines (a fungible product by quantity).
--
--  Type 1 (this migration): warehouse -> branch transfer with confirm-on-receipt:
--    draft --dispatch--> in_transit --receive--> partially_received | received
--  On dispatch the source is decremented (parts issued; bikes leave the source);
--  on receipt the destination is incremented (parts received; bikes land at the
--  branch). Receipt captures per-line received / missing / damaged (discrepancy).
--
--  Idempotent: safe as a fresh-init script and as an Alembic migration. Reuses
--  next_sales_number() for per-tenant/-year numbering (doc_type 'dispatch_note').
-- ============================================================================

CREATE TABLE IF NOT EXISTS dispatch_notes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id)      ON DELETE CASCADE,
    note_number       TEXT NOT NULL,
    dispatch_type     TEXT NOT NULL DEFAULT 'warehouse_branch_transfer' CHECK (dispatch_type IN
                        ('warehouse_branch_transfer','branch_branch_transfer',
                         'customer_delivery','internal_issuance')),
    status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                        ('draft','in_transit','partially_received','received','cancelled')),
    -- Source + destination are real stock locations (warehouses); the branch ids are
    -- kept for display + branch-scoped filtering.
    from_branch_id    UUID REFERENCES branches(id)   ON DELETE SET NULL,
    from_warehouse_id UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    to_branch_id      UUID REFERENCES branches(id)   ON DELETE SET NULL,
    to_warehouse_id   UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    remarks           TEXT,
    dispatched_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    dispatched_at     TIMESTAMPTZ,
    received_by       TEXT,           -- signature name captured at receipt
    received_by_user  UUID REFERENCES users(id) ON DELETE SET NULL,
    received_at       TIMESTAMPTZ,
    created_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, note_number)
);
CREATE INDEX IF NOT EXISTS idx_dispatch_notes_tenant_status ON dispatch_notes (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dispatch_notes_from ON dispatch_notes (from_branch_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_notes_to ON dispatch_notes (to_branch_id);

DROP TRIGGER IF EXISTS trg_dispatch_notes_updated_at ON dispatch_notes;
CREATE TRIGGER trg_dispatch_notes_updated_at
    BEFORE UPDATE ON dispatch_notes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS dispatch_note_lines (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id)        ON DELETE CASCADE,
    dispatch_note_id UUID NOT NULL REFERENCES dispatch_notes(id) ON DELETE CASCADE,
    line_kind        TEXT NOT NULL CHECK (line_kind IN ('motorcycle','part')),
    -- Spare-part line: a fungible product moved by quantity.
    product_id       UUID REFERENCES products(id) ON DELETE RESTRICT,
    -- Motorcycle line: one specific serialized unit; chassis/engine snapshot the unit.
    unit_id          UUID REFERENCES motorcycle_units(id) ON DELETE RESTRICT,
    chassis_number   TEXT,
    engine_number    TEXT,
    -- Quantities: bikes are always 1. dispatched on dispatch; received/missing/damaged
    -- captured at receipt (discrepancy). received flag confirms a serialized unit.
    dispatched_qty   NUMERIC(18,4) NOT NULL DEFAULT 0,
    received_qty     NUMERIC(18,4) NOT NULL DEFAULT 0,
    missing_qty      NUMERIC(18,4) NOT NULL DEFAULT 0,
    damaged_qty      NUMERIC(18,4) NOT NULL DEFAULT 0,
    remarks          TEXT,
    CHECK ((line_kind = 'part' AND product_id IS NOT NULL)
        OR (line_kind = 'motorcycle' AND unit_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_dispatch_note_lines_note ON dispatch_note_lines (dispatch_note_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_note_lines_unit ON dispatch_note_lines (unit_id);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (same discipline as every other business table)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['dispatch_notes','dispatch_note_lines']
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
    ('delivery_note.read',    'View delivery / dispatch notes'),
    ('delivery_note.dispatch','Create + dispatch delivery notes (send stock in transit)'),
    ('delivery_note.receive', 'Confirm receipt of delivery notes (with discrepancies)')
ON CONFLICT (code) DO NOTHING;

-- Admin, Branch Manager, Inventory Manager, Warehouse Manager: full operation.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('delivery_note.read','delivery_note.dispatch','delivery_note.receive')
WHERE r.is_system AND r.name IN ('Admin','Branch Manager','Inventory Manager','Warehouse Manager')
ON CONFLICT DO NOTHING;

-- Salesperson: read + receive (a branch confirms its incoming stock).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('delivery_note.read','delivery_note.receive')
WHERE r.is_system AND r.name = 'Salesperson'
ON CONFLICT DO NOTHING;

-- Cashier, Finance, Procurement Manager, Viewer: read-only.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'delivery_note.read'
WHERE r.is_system AND r.name IN ('Cashier','Finance','Procurement Manager','Viewer')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE dispatch_notes IS 'Typed delivery/dispatch notes: paper that documents a stock movement (transfer/delivery/issuance); never mutates stock directly.';
COMMENT ON TABLE dispatch_note_lines IS 'Delivery-note lines: motorcycle (a unit by chassis) or spare-part (a product by qty), with per-line receipt discrepancy.';
