-- ============================================================================
--  Tenant business-identity settings (multi-tenant, industry-agnostic).
--
--  The core platform is generic; everything company-specific (brand, industry,
--  currency, country, timezone, logo, and the AI assistant's name/prompt/feature
--  flags) lives here, per tenant. Idempotent; safe to re-run. `name` already holds
--  the company name and `base_currency` the default currency, so those are reused.
-- ============================================================================
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_name       TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS industry         TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS country          TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS timezone         TEXT NOT NULL DEFAULT 'UTC';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url         TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS assistant_name   TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS assistant_prompt TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS feature_flags    JSONB NOT NULL DEFAULT '{}'::jsonb;
