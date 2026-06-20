-- Auth hardening: login-lockout counters on users + refresh-token sessions.
-- Idempotent: safe to run repeatedly and alongside the fresh-init schema.

ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_count   INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until         TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_failed_login_at TIMESTAMPTZ;

-- Server-side refresh-token sessions (rotation + revocation + reuse detection).
-- Deliberately NOT under RLS: refresh runs before any tenant context exists.
CREATE TABLE IF NOT EXISTS refresh_sessions (
    id           UUID PRIMARY KEY,                                   -- == token jti
    user_id      UUID NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    family_id    UUID NOT NULL,
    issued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    replaced_by  UUID,
    user_agent   TEXT,
    ip_address   INET,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_refresh_sessions_user   ON refresh_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_sessions_family ON refresh_sessions (family_id);
