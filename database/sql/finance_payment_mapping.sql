-- ============================================================================
--  Finance — money-in wiring (PR 2): per-branch payment-method -> account mapping.
--
--  Money received is NEVER re-entered. Invoice payment lines (recorded by the sales
--  module) are the single source of money in. Finance READS them and posts a matching
--  IN movement to the account for that payment METHOD at the sale's BRANCH. This table
--  is that configurable mapping (per branch, per method) — nothing is hard-coded.
--
--  Activation is per branch: once a branch has ANY mapping, finance money-in is "on" for
--  it, and a payment whose method is NOT mapped FAILS LOUDLY (the sale is rolled back)
--  rather than silently dropping the money. A branch with no mappings is dormant, so the
--  sales module is unaffected until finance is set up.
--
--  This is tenant configuration (not a financial record), so a mapping row may be edited
--  or removed — unlike accounts/movements, which are append-only and never deleted.
--
--  Additive table only; no data changed. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS finance_payment_account_map (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id    UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    -- The sales payment method (mirrors the sales PaymentLineIn pattern).
    method       TEXT NOT NULL
                  CONSTRAINT finance_payment_map_method_ck
                  CHECK (method IN ('cash','card','mobile_money','bank_transfer','cheque','store_credit')),
    account_id   UUID NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One account per (branch, method).
    UNIQUE (tenant_id, branch_id, method)
);
CREATE INDEX IF NOT EXISTS idx_finance_payment_map_branch
    ON finance_payment_account_map (tenant_id, branch_id);

DROP TRIGGER IF EXISTS trg_finance_payment_map_updated_at ON finance_payment_account_map;
CREATE TRIGGER trg_finance_payment_map_updated_at
    BEFORE UPDATE ON finance_payment_account_map FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS + app_user grants (standard tenant isolation)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['finance_payment_account_map']
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
            -- Config, not a ledger: a mapping may be changed or removed.
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_user;', t);
        END IF;
    END LOOP;
END
$$;

COMMENT ON TABLE finance_payment_account_map IS 'Per-branch payment-method -> finance account mapping. Finance reads recorded invoice payments and posts one IN movement per line to the mapped account. Once a branch has any mapping, an unmapped method on a payment fails loudly (no silent drop). Tenant config (editable/removable), not a financial record.';
