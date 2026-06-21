-- ============================================================================
--  Conversational assistant (WhatsApp/OpenAI)  (additive, idempotent)
--
--  Backs the natural-language assistant. The LLM answers via function-calling over
--  the platform's own read services (it never touches these tables directly);
--  these tables are for conversation logging, branch-based access control, and the
--  phone->user mapping a real WhatsApp number resolves through later.
--
--    assistant_conversations  one row per chat session (channel api|whatsapp)
--    assistant_messages       transcript rows (user|assistant|tool) for logging/audit
--    user_warehouse_access    optional branch scoping — a user with NO rows sees ALL
--                             warehouses; with rows, only the listed ones
--    whatsapp_identities      phone number -> platform user (for the WhatsApp channel)
--
--  Idempotent: safe as a fresh-init script and as Alembic migration 0014.
-- ============================================================================

CREATE TABLE IF NOT EXISTS assistant_conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    channel     TEXT NOT NULL DEFAULT 'api' CHECK (channel IN ('api', 'whatsapp')),
    external_id TEXT,                       -- e.g. the WhatsApp phone number
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_assistant_conv_tenant_time ON assistant_conversations (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS assistant_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content         TEXT,
    tool_name       TEXT,                   -- set on role='tool' rows
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_assistant_msg_conv ON assistant_messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS user_warehouse_access (
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    warehouse_id UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, warehouse_id)
);
CREATE INDEX IF NOT EXISTS idx_user_wh_access_user ON user_warehouse_access (user_id);

CREATE TABLE IF NOT EXISTS whatsapp_identities (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    phone      TEXT NOT NULL UNIQUE,        -- one WhatsApp number -> one user
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- RLS + app_user grants for the new tenant tables -----------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['assistant_conversations','assistant_messages','user_warehouse_access','whatsapp_identities']
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

-- ---- Permission: assistant.use (read-only NL assistant) --------------------
INSERT INTO permissions (code, description) VALUES
    ('assistant.use', 'Use the natural-language assistant (WhatsApp / API)')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code = 'assistant.use'
WHERE r.is_system
  AND r.name IN ('Admin', 'Inventory Manager', 'Procurement Manager', 'Warehouse Manager', 'Viewer')
ON CONFLICT DO NOTHING;
