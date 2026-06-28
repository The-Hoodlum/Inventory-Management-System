-- ============================================================================
--  Stock-transfer ledger  (append-only, immutable)  — full per-line audit trail
--
--  One row per stock-affecting event of a transfer/requisition line, capturing a
--  COMPLETE snapshot (quantities, source/destination branch+location, type, reason,
--  and who acted) so the movement is auditable forever, independent of later edits
--  to the request, products, branches or locations.
--
--    event ∈ reserved | released | consumed | issued | received
--
--  Immutability is enforced at the grant level: app_user may only SELECT/INSERT
--  (no UPDATE/DELETE). Complements stock_movements (the on-hand/reserved accounting
--  ledger). Generic + industry-agnostic. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS stock_transfer_ledger (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),   -- transaction id
    tenant_id        UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
    request_id       UUID NOT NULL,                                -- the transfer (snapshot ref)
    request_number   TEXT NOT NULL,
    line_id          UUID NOT NULL,
    product_id       UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    event            TEXT NOT NULL CHECK (event IN
                       ('reserved','released','consumed','issued','received')),
    qty_requested    NUMERIC(18,4),
    qty_approved     NUMERIC(18,4),
    qty_issued       NUMERIC(18,4),
    qty_received     NUMERIC(18,4),
    qty_missing      NUMERIC(18,4),
    qty_damaged      NUMERIC(18,4),
    qty_extra        NUMERIC(18,4),
    source_branch_id    UUID,                                      -- snapshot (no FK: immutable)
    source_location_id  UUID,
    dest_branch_id      UUID,
    dest_location_id    UUID,
    transfer_type    TEXT,
    reason           TEXT,
    requested_by     UUID,
    approved_by      UUID,
    issued_by        UUID,
    received_by      UUID,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL, -- actor of THIS event
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_transfer_ledger_request ON stock_transfer_ledger (request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_transfer_ledger_product ON stock_transfer_ledger (product_id);
CREATE INDEX IF NOT EXISTS idx_transfer_ledger_event   ON stock_transfer_ledger (tenant_id, event);

-- ---- RLS + app_user grants (SELECT/INSERT only => immutable) ----------------
DO $$
BEGIN
    ALTER TABLE stock_transfer_ledger ENABLE ROW LEVEL SECURITY;
    ALTER TABLE stock_transfer_ledger FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'stock_transfer_ledger'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON stock_transfer_ledger
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        -- Append-only: read + insert, and explicitly REVOKE update/delete in case a
        -- blanket default-privilege grant (see docker/02_app_role.sql) handed them out.
        GRANT  SELECT, INSERT ON stock_transfer_ledger TO app_user;
        REVOKE UPDATE, DELETE ON stock_transfer_ledger FROM app_user;
    END IF;
END
$$;

COMMENT ON TABLE  stock_transfer_ledger       IS 'Append-only, immutable per-line transfer event log (full snapshot). app_user has SELECT/INSERT only.';
COMMENT ON COLUMN stock_transfer_ledger.event IS 'reserved | released | consumed | issued | received.';
