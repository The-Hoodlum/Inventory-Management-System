-- ============================================================================
--  Country of origin on motorcycle units.
--
--  A serialized unit can be the same model but sourced from a different country (e.g. an
--  HLX 150 built in India vs one from Congo). This records that per unit, so the model
--  catalog stays clean (one "HLX 150") while origin is tracked on each chassis. Free text
--  so any country works; no reference table required. Additive + idempotent.
-- ============================================================================

ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS country_of_origin TEXT;

COMMENT ON COLUMN motorcycle_units.country_of_origin IS 'Country this specific unit was sourced from (e.g. India, Congo, Kenya). Distinguishes same-model units of different origin without duplicating the model.';
