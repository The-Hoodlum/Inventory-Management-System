-- ============================================================================
--  Finance — transfers between accounts + cash handovers (PR 4).
--
--  TRANSFERS: move money between two accounts (e.g. banking cash: Cash in hand -> Bank).
--  Posts a PAIRED OUT + IN in ONE transaction, both linked to the same transfer record,
--  both audited. Never a one-sided adjustment. Reversible only by a reversing pair.
--
--  CASH HANDOVERS: branch cash handed to a named person / custody account. NOT a
--  "reset the till" button — it is an OUT movement of the handed-over amount from the
--  branch cash account (posted immediately, so the branch no longer holds it; the money
--  is IN TRANSIT), paired with an IN to the receiving account only once the receiver
--  CONFIRMS. A short confirmation records the discrepancy + a MANDATORY reason and posts
--  the IN for what was ACTUALLY received — never silently absorbing a shortfall. Every
--  kwacha is traceable to the person who took it. Corrections are reversing entries only.
--
--  Additive tables only; no data changed. Idempotent.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Account transfers (paired OUT + IN)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_transfers (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    from_account_id UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    to_account_id   UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    amount         NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reference_no   TEXT,
    notes          TEXT,
    status         TEXT NOT NULL DEFAULT 'completed'
                    CONSTRAINT account_transfers_status_ck CHECK (status IN ('completed','reversed')),
    reversed_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    reversed_at    TIMESTAMPTZ,
    reverse_reason TEXT,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT account_transfers_distinct_ck CHECK (from_account_id <> to_account_id)
);
CREATE INDEX IF NOT EXISTS idx_account_transfers_tenant ON account_transfers (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_account_transfers_accounts ON account_transfers (from_account_id, to_account_id);

-- ---------------------------------------------------------------------------
-- Cash handovers (two-sided: OUT on record, IN on confirm)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cash_handovers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id           UUID REFERENCES branches(id) ON DELETE RESTRICT,
    from_account_id     UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    to_account_id       UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    amount              NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    handover_datetime   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Who physically handed the cash over: the recording user + a recorded name/role.
    handed_over_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    handed_over_by_name TEXT,
    -- The person in charge of the money — ALWAYS a recorded name (account optional).
    received_by_name    TEXT NOT NULL,
    received_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    reference_no        TEXT,
    notes               TEXT,
    denomination_breakdown JSONB,                     -- optional note/coin counts
    status              TEXT NOT NULL DEFAULT 'PENDING_CONFIRMATION'
                         CONSTRAINT cash_handovers_status_ck
                         CHECK (status IN ('PENDING_CONFIRMATION','CONFIRMED','DISPUTED')),
    confirmed_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at        TIMESTAMPTZ,
    confirmed_amount    NUMERIC(18,4),
    discrepancy_amount  NUMERIC(18,4),
    discrepancy_reason  TEXT,
    -- A correction is a reversing pair (never an edit/delete of a confirmed handover).
    reversed_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    reversed_at         TIMESTAMPTZ,
    reverse_reason      TEXT,
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cash_handovers_tenant_branch
    ON cash_handovers (tenant_id, branch_id, handover_datetime DESC);
CREATE INDEX IF NOT EXISTS idx_cash_handovers_status ON cash_handovers (tenant_id, status);

DROP TRIGGER IF EXISTS trg_cash_handovers_updated_at ON cash_handovers;
CREATE TRIGGER trg_cash_handovers_updated_at
    BEFORE UPDATE ON cash_handovers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Optional signed-slip photo (0..1 per handover; bytes in-DB, like ImportFile).
CREATE TABLE IF NOT EXISTS cash_handover_attachments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    handover_id   UUID NOT NULL REFERENCES cash_handovers(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_type  TEXT,
    data          BYTEA NOT NULL,
    uploaded_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (handover_id)
);

DROP TRIGGER IF EXISTS trg_cash_handover_attachments_updated_at ON cash_handover_attachments;
CREATE TRIGGER trg_cash_handover_attachments_updated_at
    BEFORE UPDATE ON cash_handover_attachments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['account_transfers','cash_handovers','cash_handover_attachments']
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
            -- No DELETE: transfers/handovers are reversed, never deleted; an attachment may
            -- be replaced (UPDATE).
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO app_user;', t);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- Permissions + role grants
-- ---------------------------------------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('finance.transfer', 'Move money between finance accounts (and reverse a transfer)'),
    ('finance.handover', 'Record and confirm cash handovers')
ON CONFLICT (code) DO NOTHING;

-- Transfers: managers (Admin, Finance, Branch Manager).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'finance.transfer'
WHERE r.is_system AND r.name IN ('Admin','Finance','Branch Manager')
ON CONFLICT DO NOTHING;

-- Handovers: managers + Cashier (a cashier hands over their till; a manager/accountant confirms).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'finance.handover'
WHERE r.is_system AND r.name IN ('Admin','Finance','Branch Manager','Cashier')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE account_transfers IS 'Money moved between two accounts: one transfer record backing a PAIRED OUT + IN in a single transaction. Reversible only by a reversing pair.';
COMMENT ON TABLE cash_handovers IS 'Branch cash handed to a named person / custody account. OUT posted on record (money in transit; branch no longer holds it), IN posted on confirm. A short confirmation records a discrepancy + mandatory reason and posts the IN for what was actually received. Every kwacha traceable to who took it.';
