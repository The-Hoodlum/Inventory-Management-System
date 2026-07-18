-- ============================================================================
--  Finance — cash & bank position (a CASH BOOK / treasury ledger, NOT full
--  double-entry accounting).
--
--  PR 1 of the finance module: ACCOUNTS + an APPEND-ONLY MOVEMENT LEDGER.
--
--  Every account (cash in hand, a bank account, a mobile-money wallet, a custody
--  account) is an append-only ledger, exactly like the stock ledger:
--
--      balance == opening_balance + sum(IN) - sum(OUT)
--
--  The balance is ALWAYS DERIVED by summing movements — it is never stored as an
--  editable field and no endpoint may set / edit / zero it. If a balance changes,
--  a movement explains it. Corrections are REVERSING entries (movements.reversal_of),
--  never deletes — there is no hard-delete path for any financial record.
--
--  Branch-scoped throughout: cash in hand is per branch; CUSTODY accounts (office /
--  head-office / accountant custody) may be tenant-wide (branch_id NULL) so a branch
--  can hand cash over to them. The user creates & names every account themselves —
--  nothing is hard-coded.
--
--  Additive tables only; no data changed. Idempotent.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Accounts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_accounts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- The site this account belongs to. Required for CASH / BANK / MOBILE_MONEY (cash in
    -- hand is per branch); NULL is allowed for a CUSTODY account that is tenant-wide
    -- (office / head-office / accountant custody). Enforced in the service layer.
    branch_id        UUID REFERENCES branches(id) ON DELETE RESTRICT,
    name             TEXT NOT NULL,
    type             TEXT NOT NULL
                      CONSTRAINT financial_accounts_type_ck
                      CHECK (type IN ('CASH','BANK','MOBILE_MONEY','CUSTODY')),
    currency         TEXT NOT NULL DEFAULT 'ZMW',
    -- The reconstructed starting balance and the date it is 'as of'. Part of the DERIVED
    -- balance (opening + IN - OUT); set once at creation and never edited afterwards
    -- (editing it would be editing a balance, which is forbidden).
    opening_balance  NUMERIC(18,4) NOT NULL DEFAULT 0,
    opening_as_of    DATE,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_financial_accounts_tenant_branch
    ON financial_accounts (tenant_id, branch_id, is_active);
CREATE INDEX IF NOT EXISTS idx_financial_accounts_type ON financial_accounts (tenant_id, type);

DROP TRIGGER IF EXISTS trg_financial_accounts_updated_at ON financial_accounts;
CREATE TRIGGER trg_financial_accounts_updated_at
    BEFORE UPDATE ON financial_accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Movements (immutable, append-only) — the ONLY thing that changes a balance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_movements (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- RESTRICT: an account is never deleted, so its ledger can never be orphaned.
    account_id     UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    -- direction carries the sign; amount is ALWAYS POSITIVE.
    direction      TEXT NOT NULL
                    CONSTRAINT account_movements_direction_ck CHECK (direction IN ('IN','OUT')),
    amount         NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    category       TEXT,                                  -- e.g. sale_payment, expense, transfer, handover
    -- Link back to the source document that caused the movement.
    reference_type TEXT,                                  -- invoice_payment | expense | transfer | handover | ...
    reference_id   UUID,
    description    TEXT,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A correction NEVER edits or deletes the original: it is a NEW movement in the
    -- opposite direction that points back at the one it cancels.
    reversal_of    UUID REFERENCES account_movements(id) ON DELETE RESTRICT
);
-- The statement / running-balance query: an account's movements in time order.
CREATE INDEX IF NOT EXISTS idx_account_movements_account
    ON account_movements (tenant_id, account_id, occurred_at, created_at);
CREATE INDEX IF NOT EXISTS idx_account_movements_reference
    ON account_movements (reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_account_movements_reversal ON account_movements (reversal_of);

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['financial_accounts','account_movements']
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
            -- No DELETE on movements: the ledger is append-only. Accounts are deactivated,
            -- never deleted, but we keep DELETE off financial_accounts too (no wipe path).
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO app_user;', t);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- Permissions + role grants
-- ---------------------------------------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('finance.read',           'View finance accounts, balances, statements and reports'),
    ('finance.account.manage', 'Create / edit / deactivate finance accounts')
ON CONFLICT (code) DO NOTHING;

-- Admin & Finance: full finance access.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN
    ('finance.read','finance.account.manage')
WHERE r.is_system AND r.name IN ('Admin','Finance')
ON CONFLICT DO NOTHING;

-- Branch Manager: view finance within their branch scope (no account admin).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'finance.read'
WHERE r.is_system AND r.name = 'Branch Manager'
ON CONFLICT DO NOTHING;

COMMENT ON TABLE financial_accounts IS 'Finance accounts (cash / bank / mobile money / custody). An append-only ledger each: balance is DERIVED (opening_balance + sum(IN) - sum(OUT)), never stored or set. Branch-scoped; CUSTODY may be tenant-wide.';
COMMENT ON TABLE account_movements IS 'Immutable, append-only money movements — the ONLY thing that changes an account balance. amount is always positive; direction (IN/OUT) carries the sign. Corrections are reversing entries (reversal_of), never edits or deletes.';
