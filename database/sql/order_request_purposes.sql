-- ============================================================================
--  Order Request — extended request types (additive, idempotent)
--
--  Adds 'branch_transfer' and 'stock_adjustment' to the allowed request purposes,
--  alongside the existing for_sale / shelf_replenishment / workshop_use / office_use
--  / other. Generic and industry-agnostic — no tenant- or sector-specific values.
--
--  branch_transfer's source -> destination movement logic lands in a later phase;
--  this only widens the allowed set so the type can be selected and recorded.
-- ============================================================================

ALTER TABLE request_headers DROP CONSTRAINT IF EXISTS request_headers_purpose_check;
ALTER TABLE request_headers ADD CONSTRAINT request_headers_purpose_check
    CHECK (purpose IN
        ('for_sale', 'shelf_replenishment', 'workshop_use', 'office_use',
         'branch_transfer', 'stock_adjustment', 'other'));
