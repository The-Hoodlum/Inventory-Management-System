-- ============================================================================
--  Tenant branding colors (additive, idempotent). Part of the generic
--  business-identity settings; e.g. {"primary": "#0a7", "secondary": "#333"}.
-- ============================================================================
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS branding_colors JSONB NOT NULL DEFAULT '{}'::jsonb;
