-- ============================================================================
--  Motorcycle bulk import: provenance columns on motorcycle_units (additive,
--  idempotent).
--
--  A unit created by a spreadsheet import records the job that created it
--  (import_job_id) and, when the row carried a historical sale/hold set directly
--  from the sheet (status sold/reserved with customer + dates) rather than through
--  the live sales flow, is flagged imported_historical so reports can tell
--  back-filled records from live ones.
--
--  No data is deleted here; these are purely additive columns.
-- ============================================================================
ALTER TABLE motorcycle_units
    ADD COLUMN IF NOT EXISTS imported_historical BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE motorcycle_units
    ADD COLUMN IF NOT EXISTS import_job_id UUID REFERENCES import_jobs(id) ON DELETE SET NULL;

-- Historical lifecycle dates carried by back-filled rows (no column existed for them).
ALTER TABLE motorcycle_units
    ADD COLUMN IF NOT EXISTS assembled_date DATE;

ALTER TABLE motorcycle_units
    ADD COLUMN IF NOT EXISTS date_sold DATE;

CREATE INDEX IF NOT EXISTS idx_motorcycle_units_import_job ON motorcycle_units (import_job_id);

COMMENT ON COLUMN motorcycle_units.imported_historical IS
    'True when the unit was back-filled from a spreadsheet with a sale/hold set directly (not through the live sales flow).';
COMMENT ON COLUMN motorcycle_units.import_job_id IS
    'The data-import job that created this unit, when it came from a bulk import.';
COMMENT ON COLUMN motorcycle_units.date_sold IS
    'Historical sale date for a back-filled sold unit (live sales use the invoice date).';
