-- ============================================================================
--  Bike lines in quotations — a quotation line can quote a serialized motorcycle (by
--  unit) instead of a fungible product, so a single quote can mix bikes and parts.
--
--  product_id becomes nullable and a nullable unit_id is added; exactly one of the two
--  identifies the line (part vs bike). Additive + idempotent; no data changed (every
--  existing line has a product_id, satisfying the new check).
-- ============================================================================

ALTER TABLE quotation_lines ALTER COLUMN product_id DROP NOT NULL;
ALTER TABLE quotation_lines ADD COLUMN IF NOT EXISTS unit_id UUID REFERENCES motorcycle_units(id) ON DELETE RESTRICT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quotation_lines_part_or_bike_ck') THEN
        ALTER TABLE quotation_lines ADD CONSTRAINT quotation_lines_part_or_bike_ck
            CHECK ((product_id IS NOT NULL) <> (unit_id IS NOT NULL));
    END IF;
END
$$;

COMMENT ON COLUMN quotation_lines.unit_id IS 'The serialized motorcycle quoted on this line (bike line); mutually exclusive with product_id (part line).';
