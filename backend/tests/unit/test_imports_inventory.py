"""The inventory target's row processing, exercised with a fake context (no DB)."""
from __future__ import annotations

from decimal import Decimal

from app.imports.domain.fields import ROW_IMPORTED, ROW_SKIPPED
from app.imports.domain.registry import get_importer

import app.imports.targets  # noqa: F401  (registers the inventory target)

IMPORTER = get_importer("inventory")


class _Warehouse:
    def __init__(self, wid="wh-1"):
        self.id = wid


class _Product:
    def __init__(self, pid):
        self.id = pid


class FakeCtx:
    """Records what the target asks it to persist."""

    def __init__(self, warehouse=_Warehouse()):
        self._warehouse = warehouse
        self.products: list[dict] = []
        self.stock: list[dict] = []

    async def resolve_warehouse(self, name):
        return self._warehouse

    async def resolve_supplier(self, name):
        return f"sup:{name}" if name else None

    async def get_or_create_category(self, name):
        return f"cat:{name}" if name else None

    async def get_or_create_brand(self, name):
        return f"brand:{name}" if name else None

    async def upsert_product(self, *, sku, attrs, category, brand, supplier):
        self.products.append(
            {"sku": sku, "attrs": attrs, "category": category, "brand": brand, "supplier": supplier}
        )
        return _Product(sku)

    async def set_initial_stock(self, *, product, warehouse, qty, unit_cost):
        self.stock.append(
            {"product": product.id, "warehouse": warehouse.id, "qty": qty, "unit_cost": unit_cost}
        )


async def test_process_row_imports_product_and_stock():
    ctx = FakeCtx()
    clean = {
        "sku": "A-1", "name": "Widget", "quantity": Decimal("12"),
        "cost_price": Decimal("3.50"), "category": "Hardware", "brand": "Acme",
        "supplier": "Globex", "commodity_tag": ["steel"], "reorder_point": 5,
    }
    result = await IMPORTER.process_row(ctx, clean)

    assert result.status == ROW_IMPORTED
    assert result.sku == "A-1"
    assert len(ctx.products) == 1
    p = ctx.products[0]
    assert p["sku"] == "A-1"
    assert p["attrs"]["name"] == "Widget"
    assert p["attrs"]["cost_price"] == Decimal("3.50")
    assert p["attrs"]["commodity_tags"] == ["steel"]   # field -> column rename applied
    assert p["attrs"]["reorder_point"] == 5
    assert p["category"] == "cat:Hardware" and p["brand"] == "brand:Acme"
    assert p["supplier"] == "sup:Globex"
    # stock recorded once, qty positive, cost forwarded as unit_cost
    assert ctx.stock == [{"product": "A-1", "warehouse": "wh-1", "qty": Decimal("12"), "unit_cost": Decimal("3.50")}]


async def test_process_row_skips_when_warehouse_unresolved():
    ctx = FakeCtx(warehouse=None)
    result = await IMPORTER.process_row(ctx, {"sku": "A-1", "name": "Widget", "quantity": Decimal("5")})
    assert result.status == ROW_SKIPPED
    assert ctx.products == [] and ctx.stock == []


async def test_zero_quantity_creates_product_but_no_movement():
    ctx = FakeCtx()
    result = await IMPORTER.process_row(ctx, {"sku": "A-1", "name": "Widget", "quantity": Decimal("0")})
    assert result.status == ROW_IMPORTED
    assert len(ctx.products) == 1
    assert ctx.stock == []  # no movement for zero opening stock


async def test_currency_only_applied_when_valid_three_letter():
    ctx = FakeCtx()
    await IMPORTER.process_row(ctx, {"sku": "A-1", "name": "W", "quantity": Decimal("1"), "currency": "usd"})
    assert ctx.products[0]["attrs"]["currency"] == "USD"

    ctx2 = FakeCtx()
    await IMPORTER.process_row(ctx2, {"sku": "A-2", "name": "W", "quantity": Decimal("1"), "currency": "Dollar"})
    assert "currency" not in ctx2.products[0]["attrs"]
