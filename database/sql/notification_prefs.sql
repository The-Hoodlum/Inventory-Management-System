-- ============================================================================
--  Notification preferences — per-user channel settings for notifications.
--
--  In-app notifications are always delivered (the bell/inbox is the system of record).
--  This table only governs the OPT-IN side channels: today, whether a user receives the
--  WhatsApp push of critical notifications. A user with no row uses the defaults (push on
--  when they've registered a number), so the table is sparse — only opt-OUTs are stored.
--
--  Additive table only; no data changed. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS notification_prefs (
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    whatsapp_push BOOLEAN NOT NULL DEFAULT true,   -- receive the WhatsApp push of critical events
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['notification_prefs']
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

COMMENT ON TABLE notification_prefs IS 'Per-user notification channel preferences. In-app is always on; this stores opt-outs for side channels (WhatsApp push of critical events). Sparse — no row = defaults.';
