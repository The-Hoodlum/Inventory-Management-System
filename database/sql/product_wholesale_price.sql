-- Wholesale price on products.
--
-- Products already carry a cost price and a selling (retail) price; this adds a third tier,
-- the wholesale price, for trade/bulk customers. Additive and defaulted so every existing
-- product, writer, and reader is unaffected (a product with no wholesale price reads 0).

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS wholesale_price NUMERIC(18,4) NOT NULL DEFAULT 0
        CHECK (wholesale_price >= 0);

COMMENT ON COLUMN products.wholesale_price IS 'Trade/bulk price tier, alongside cost_price and selling_price (retail).';
