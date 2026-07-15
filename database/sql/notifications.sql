-- ============================================================================
--  Notifications — event-driven, per-recipient in-app notifications.
--
--  A generic core: a producer service emits an event (event_type + a small payload),
--  the notification service resolves recipients (by role/permission + branch), and ONE
--  row is stored per recipient so read/unread is personal. This is separate from the
--  COMPUTED operational signals (low stock, pending approvals) the bell already derives
--  on the fly — the bell merges both. No producer writes here yet (shipped inert); the
--  first producers (assembly events) wire in a later change.
--
--  Additive table only; no data changed. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- The person who should see it. One row per recipient -> personal read state.
    recipient_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type        TEXT NOT NULL,                       -- e.g. bike.sold_before_assembly
    severity          TEXT NOT NULL DEFAULT 'info'
                       CONSTRAINT notifications_severity_ck CHECK (severity IN ('info','warning','critical')),
    title             TEXT NOT NULL,                       -- what happened (rendered by the producer)
    body              TEXT,                                -- optional detail line
    href              TEXT,                                -- where it's actioned (a frontend route)
    entity_type       TEXT,                                -- what it's about: unit | invoice | delivery | ...
    entity_id         UUID,
    branch_id         UUID REFERENCES branches(id) ON DELETE SET NULL,
    actor_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,   -- who triggered it (nullable)
    read_at           TIMESTAMPTZ,                          -- NULL = unread
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The bell query: my unread + recent, newest first.
CREATE INDEX IF NOT EXISTS idx_notifications_recipient
    ON notifications (tenant_id, recipient_user_id, read_at, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_entity ON notifications (entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['notifications']
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

COMMENT ON TABLE notifications IS 'Event-driven, per-recipient in-app notifications. One row per recipient (personal read/unread). Emitted by the notification service when a producer service acts; separate from the computed operational signals the bell also shows.';
