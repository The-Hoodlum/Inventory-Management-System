-- ============================================================================
--  Import framework Phase 2: allow the 'rolled_back' job status (additive, idempotent).
--  Everything else Phase 2 needs (import_mappings, products.created_by_import_job_id,
--  the initial_import movement type) already exists from migration 0011.
-- ============================================================================
ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_status_check;
ALTER TABLE import_jobs ADD  CONSTRAINT import_jobs_status_check
    CHECK (status IN ('pending','running','completed','cancelled','failed','rolled_back'));
