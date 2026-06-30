-- ============================================================================
--  Order Request — source -> destination transfers (additive, idempotent)
--
--  A branch_transfer request moves stock FROM its branch (the source location)
--  TO a destination location. At issue time the source is debited and the
--  destination credited, with paired stock movements (from/to) for a full ledger.
--
--  destination_branch_id is nullable — only branch_transfer requests use it; all
--  other request types behave exactly as before. Generic + industry-agnostic.
-- ============================================================================

ALTER TABLE request_headers
    ADD COLUMN IF NOT EXISTS destination_branch_id UUID REFERENCES warehouses(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_req_destination ON request_headers (destination_branch_id);
