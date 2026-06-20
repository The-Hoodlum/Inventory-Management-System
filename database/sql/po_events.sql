-- ============================================================================
--  Purchase-order lifecycle timeline  (additive, idempotent)
--
--  An append-only, queryable history of every PO action (submit/approve/reject/
--  cancel/send/receive/close) with actor, timestamps, status change, an optional
--  comment, and structured detail (e.g. received quantities). Complements the
--  generic audit_logs table.
--
--  Idempotent so it is safe to run both as a fresh-init script (docker-compose)
--  and as Alembic migration 0003 on an already-provisioned database.
-- ============================================================================

CREATE TABLE IF NOT EXISTS purchase_order_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id)          ON DELETE CASCADE,
    po_id       UUID NOT NULL REFERENCES purchase_orders(id)  ON DELETE CASCADE,
    action      TEXT NOT NULL,            -- created|updated|submitted|approved|rejected|cancelled|sent|received|closed
    from_status TEXT,
    to_status   TEXT,
    comment     TEXT,
    detail      JSONB,
    actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_po_events_po     ON purchase_order_events (po_id, created_at);
CREATE INDEX IF NOT EXISTS idx_po_events_tenant ON purchase_order_events (tenant_id);

-- Row-Level Security (tenant isolation), matching the rest of the schema.
ALTER TABLE purchase_order_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order_events FORCE  ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'purchase_order_events'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON purchase_order_events
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
END
$$;

-- Grant to the application role when it exists (no-op otherwise).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_order_events TO app_user;
    END IF;
END
$$;
