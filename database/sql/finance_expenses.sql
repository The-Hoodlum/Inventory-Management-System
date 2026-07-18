-- ============================================================================
--  Finance — expenses (PR 3): money OUT, manager-recorded, no approval workflow.
--
--  An expense is money leaving one of the finance accounts (fuel, rent, salaries, …).
--  Recording one posts an OUT movement against the chosen account through the ONE
--  append-only ledger, so cash in hand drops immediately and correctly.
--
--  Rules honoured here:
--   • MANAGER-ONLY create/edit (permission finance.expense.manage); anyone with
--     finance.read may VIEW within their branch scope. No approval step.
--   • Categories are a CONFIGURABLE tenant list (not hard-coded) — deactivated, never
--     deleted (they're referenced by expense records).
--   • CORRECTIONS ARE REVERSALS: an expense is voided (posting a reversing IN that
--     restores the balance) and re-recorded — never edited in amount, never deleted.
--     There is no hard-delete path for any expense record.
--   • Branch-scoped throughout.
--
--  Additive tables only; no data changed. Idempotent.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Configurable category list
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

DROP TRIGGER IF EXISTS trg_expense_categories_updated_at ON expense_categories;
CREATE TRIGGER trg_expense_categories_updated_at
    BEFORE UPDATE ON expense_categories FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Expenses (money out; each posts an OUT movement to its account)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expenses (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id     UUID REFERENCES branches(id) ON DELETE RESTRICT,
    -- The account it was paid FROM (its balance drops by exactly the amount).
    account_id    UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    amount        NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    expense_date  DATE NOT NULL,
    category_id   UUID REFERENCES expense_categories(id) ON DELETE RESTRICT,
    payee         TEXT,
    description   TEXT,
    reference_no  TEXT,
    status        TEXT NOT NULL DEFAULT 'recorded'
                   CONSTRAINT expenses_status_ck CHECK (status IN ('recorded','voided')),
    recorded_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    -- A void is a REVERSAL (not a delete): the OUT is cancelled by a reversing IN and the
    -- record is marked voided, with who/when/why kept.
    void_reason   TEXT,
    voided_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    voided_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_expenses_tenant_branch_date
    ON expenses (tenant_id, branch_id, expense_date DESC);
CREATE INDEX IF NOT EXISTS idx_expenses_account ON expenses (account_id);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses (category_id);

DROP TRIGGER IF EXISTS trg_expenses_updated_at ON expenses;
CREATE TRIGGER trg_expenses_updated_at
    BEFORE UPDATE ON expenses FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Receipt attachment (0..1 per expense; bytes stored in-DB like ImportFile)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_attachments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    expense_id    UUID NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_type  TEXT,
    data          BYTEA NOT NULL,
    uploaded_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (expense_id)
);

DROP TRIGGER IF EXISTS trg_expense_attachments_updated_at ON expense_attachments;
CREATE TRIGGER trg_expense_attachments_updated_at
    BEFORE UPDATE ON expense_attachments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['expense_categories','expenses','expense_attachments']
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
            -- No DELETE: expenses are voided (reversed), never deleted; categories are
            -- deactivated. An attachment may be replaced (UPDATE), not removed.
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO app_user;', t);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- Permissions + role grants
-- ---------------------------------------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('finance.expense.manage', 'Record / edit / void expenses and manage expense categories (managers)')
ON CONFLICT (code) DO NOTHING;

-- Managers record + manage expenses (no approval step). Admin, Finance, Branch Manager.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'finance.expense.manage'
WHERE r.is_system AND r.name IN ('Admin','Finance','Branch Manager')
ON CONFLICT DO NOTHING;

-- Cashier gets finance.read: a non-manager who may VIEW finance (accounts, expenses)
-- within their branch scope, but cannot record/edit — the "non-managers may view" rule.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'finance.read'
WHERE r.is_system AND r.name = 'Cashier'
ON CONFLICT DO NOTHING;

COMMENT ON TABLE expenses IS 'Money-out records. Recording one posts an OUT movement to its account (append-only ledger), dropping the balance by exactly the amount. Manager-recorded (finance.expense.manage), no approval. Corrections are voids (reversing IN), never edits of amount or deletes.';
COMMENT ON TABLE expense_categories IS 'Configurable tenant expense category list (fuel, rent, salaries, …). Deactivated, never deleted.';
COMMENT ON TABLE expense_attachments IS 'Optional receipt image/PDF per expense (bytes stored in-DB). Replaceable, not deletable.';
