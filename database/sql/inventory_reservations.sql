-- ============================================================================
--  Inventory reservations  (additive, idempotent)  — Phase 2b
--
--  Holds stock between the moment a demand is committed (e.g. an order request is
--  approved) and the moment it is physically issued. A reservation reduces a
--  product's AVAILABLE quantity without touching ON-HAND, so the same units cannot
--  be promised twice.
--
--    inventory_reservations   one row per held quantity (status workflow + who/when)
--
--  The running total of ACTIVE reservations is denormalised onto
--  inventory.qty_reserved (maintained transactionally by the app, exactly as
--  inventory.qty_on_hand mirrors the stock_movements ledger). The generated
--  column inventory.qty_available = qty_on_hand - qty_reserved - qty_damaged then
--  self-corrects. Paired 'reserve' / 'unreserve' stock movements (already allowed
--  by the stock_movements CHECK) give a full audit trail.
--
--  Generic + industry-agnostic. Idempotent: safe as a fresh-init script and as an
--  Alembic migration.
-- ============================================================================

CREATE TABLE IF NOT EXISTS inventory_reservations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id)    ON DELETE CASCADE,
    product_id     UUID NOT NULL REFERENCES products(id)   ON DELETE RESTRICT,
    warehouse_id   UUID NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    qty            NUMERIC(18,4) NOT NULL CHECK (qty >= 0),  -- currently-held remaining; 0 once fully consumed/released
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                     ('active','consumed','released','expired')),
    reference_type TEXT,                              -- 'order_request', 'manual', ...
    reference_id   UUID,                              -- what holds the stock
    expires_at     TIMESTAMPTZ,                       -- optional auto-release horizon
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at    TIMESTAMPTZ                        -- when it left 'active' (consumed/released/expired)
);

CREATE INDEX IF NOT EXISTS idx_reservations_inv
    ON inventory_reservations (product_id, warehouse_id, status);
CREATE INDEX IF NOT EXISTS idx_reservations_reference
    ON inventory_reservations (reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_reservations_tenant_status
    ON inventory_reservations (tenant_id, status);
-- Active reservations with an expiry, for the (future) auto-release sweep.
CREATE INDEX IF NOT EXISTS idx_reservations_expiry
    ON inventory_reservations (expires_at)
    WHERE status = 'active' AND expires_at IS NOT NULL;

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
BEGIN
    ALTER TABLE inventory_reservations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE inventory_reservations FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'inventory_reservations'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON inventory_reservations
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON inventory_reservations TO app_user;
    END IF;
END
$$;

COMMENT ON TABLE  inventory_reservations            IS 'Held stock: reduces qty_available without moving qty_on_hand, until consumed or released.';
COMMENT ON COLUMN inventory_reservations.status     IS 'active -> consumed (issued) | released (cancelled) | expired (timed out).';
COMMENT ON COLUMN inventory_reservations.expires_at IS 'Optional auto-release horizon; NULL = never expires.';
