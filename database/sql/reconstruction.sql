-- Reconstruction support on the stock ledger.
--
-- History reconstruction (opening balances + a chronological transaction replay) writes
-- through the SAME inventory core as live operations, but each ledger entry needs to carry
-- (a) the BUSINESS moment it happened at (``occurred_at``, back-dated to the source
-- document's date — distinct from ``created_at``, the row-insert time), and (b) a flag that
-- it was reconstructed rather than captured live (``imported_historical``). Both are additive
-- and nullable/defaulted so every existing writer and reader is unaffected.
--
-- Also whitelists the ``opening_balance`` movement type used to seed stock as of a period
-- start (an inflow, like a receipt, but semantically the reconstruction's initial entry).

ALTER TABLE stock_movements
    ADD COLUMN IF NOT EXISTS occurred_at          TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS imported_historical  BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN stock_movements.occurred_at IS
    'Business moment the movement happened (back-dated for reconstructed history); NULL falls back to created_at.';
COMMENT ON COLUMN stock_movements.imported_historical IS
    'True when the entry was written by history reconstruction (opening balance / replay) rather than a live op.';

-- Order reconstructed history by when it actually happened.
CREATE INDEX IF NOT EXISTS idx_movements_product_occurred
    ON stock_movements (product_id, warehouse_id, occurred_at);

-- Allow the opening-balance seed type alongside the existing set (which already includes
-- 'initial_import' from the inventory import).
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_movement_type_check;
ALTER TABLE stock_movements ADD  CONSTRAINT stock_movements_movement_type_check
    CHECK (movement_type IN
        ('receipt','issue','adjustment','transfer_in','transfer_out',
         'damage','reserve','unreserve','initial_import','opening_balance'));
