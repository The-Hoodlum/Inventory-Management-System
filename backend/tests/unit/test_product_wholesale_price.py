"""Unit checks for the wholesale price: the inventory import field + product schema."""
from __future__ import annotations

from decimal import Decimal

from app.imports.domain.registry import get_importer
from app.imports.targets import inventory as _inventory  # noqa: F401  (registers)
from app.schemas.product import ProductCreate


def test_inventory_import_exposes_wholesale_price_with_aliases():
    imp = get_importer("inventory")
    field = next((f for f in imp.fields if f.name == "wholesale_price"), None)
    assert field is not None, "inventory import should expose a wholesale_price field"
    assert field.label == "Wholesale Price"
    assert "wholesale" in field.aliases


def test_product_create_defaults_wholesale_to_zero_and_accepts_a_value():
    assert ProductCreate(sku="X", name="Item").wholesale_price == Decimal("0")
    p = ProductCreate(sku="X", name="Item", cost_price=Decimal("2.26"),
                      selling_price=Decimal("6.44"), wholesale_price=Decimal("5.08"))
    assert p.wholesale_price == Decimal("5.08")
