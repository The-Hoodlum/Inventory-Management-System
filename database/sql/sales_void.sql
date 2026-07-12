-- ============================================================================
--  Sale VOID / reverse — an admin can reverse a sale (correct a mistake) WITHOUT a hard
--  delete. The invoice stays for audit, marked 'voided', with who/when/why recorded; the
--  stock it moved is restored through the one InventoryService write path, and a voided
--  bike returns to an available status. Voided sales are excluded from active totals.
--
--  This just records the void metadata on the invoice. Additive + idempotent.
-- ============================================================================

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS voided_at   TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS voided_by   UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS void_reason TEXT;

-- Allow the new 'voided' status (the status CHECK predates it).
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_status_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_status_check CHECK (
    status IN ('draft', 'sent', 'partially_paid', 'paid', 'overdue', 'cancelled', 'voided')
);

COMMENT ON COLUMN invoices.void_reason IS 'Why the sale was voided (mandatory at void time). The invoice is kept for audit but excluded from active sales.';
