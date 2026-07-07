-- User -> branch scoping.
--
-- A user assigned to one or more branches may only see/act on those branches' data. A user
-- with NO rows is UNRESTRICTED (all branches) — owners/admins. This is the server-side
-- boundary the branch switcher + every branch-filtered module validate against; it is
-- branch-level (a location/warehouse is in scope when its branch is). Additive; the existing
-- warehouse-level user_warehouse_access (assistant) is untouched.

CREATE TABLE IF NOT EXISTS user_branch_access (
    tenant_id  UUID NOT NULL REFERENCES tenants(id)   ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id)     ON DELETE CASCADE,
    branch_id  UUID NOT NULL REFERENCES branches(id)  ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, branch_id)
);
CREATE INDEX IF NOT EXISTS idx_user_branch_access_user ON user_branch_access (user_id);

COMMENT ON TABLE user_branch_access IS
    'User -> branch grants. No rows for a user = unrestricted (all branches).';

-- ---- RLS + app_user grants -------------------------------------------------
DO $$
BEGIN
    ALTER TABLE user_branch_access ENABLE ROW LEVEL SECURITY;
    ALTER TABLE user_branch_access FORCE  ROW LEVEL SECURITY;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'user_branch_access' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON user_branch_access
            USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON user_branch_access TO app_user;
    END IF;
END
$$;
