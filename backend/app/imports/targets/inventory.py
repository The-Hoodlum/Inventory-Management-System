"""The "inventory" import target: load a product catalog + opening stock from a
spreadsheet. First registration on the generic framework.

Each row becomes (or updates) a Product, optionally links Category/Brand/Supplier
and a Warehouse, and records opening stock as an ``initial_import`` movement. Field
aliases drive auto-detection (e.g. SKU ← "Part No", Quantity ← "On Hand").
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.imports.domain.base import ImportRowContext, ResourceImporter
from app.imports.domain.fields import (
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_STANDARD,
    FieldKind,
    FieldSpec,
    RowResult,
)
from app.imports.domain.registry import register

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)
_ADV = (LEVEL_ADVANCED,)

_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sku", "SKU", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("item code", "product code", "part number", "part no", "code",
                       "item no", "item number", "product id", "stock code")),
    FieldSpec("name", "Item Name", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("product name", "item", "product", "title", "item description")),
    FieldSpec("quantity", "Quantity On Hand", required=True, kind=FieldKind.DECIMAL, levels=_ALL,
              aliases=("qty", "quantity", "stock", "on hand", "onhand", "inventory",
                       "qty available", "available", "stock on hand", "qty on hand")),
    FieldSpec("description", "Description", kind=FieldKind.STRING, levels=_STD,
              aliases=("desc", "details", "long description")),
    FieldSpec("warehouse", "Warehouse", kind=FieldKind.STRING, levels=_STD,
              aliases=("location", "store", "branch", "site", "warehouse name")),
    FieldSpec("supplier", "Supplier", kind=FieldKind.STRING, levels=_STD,
              aliases=("vendor", "manufacturer", "supplier name")),
    FieldSpec("cost_price", "Cost Price", kind=FieldKind.DECIMAL, levels=_STD,
              aliases=("cost", "unit cost", "buy price", "purchase price", "cost per unit")),
    FieldSpec("reorder_point", "Reorder Point", kind=FieldKind.INTEGER, levels=_STD,
              aliases=("rop", "reorder level", "min stock", "minimum stock", "reorder")),
    FieldSpec("unit_of_measure", "Unit of Measure", kind=FieldKind.STRING, levels=_ADV,
              aliases=("uom", "unit", "units", "measure", "unit of measure")),
    FieldSpec("selling_price", "Selling Price", kind=FieldKind.DECIMAL, levels=_ADV,
              aliases=("price", "sell price", "retail price", "sale price", "unit price")),
    FieldSpec("currency", "Currency", kind=FieldKind.STRING, levels=_ADV,
              aliases=("ccy", "currency code")),
    FieldSpec("category", "Category", kind=FieldKind.STRING, levels=_ADV,
              aliases=("group", "product category", "type", "class")),
    FieldSpec("brand", "Brand", kind=FieldKind.STRING, levels=_ADV,
              aliases=("make",)),
    FieldSpec("barcode", "Barcode", kind=FieldKind.STRING, levels=_ADV,
              aliases=("ean", "upc", "gtin")),
    FieldSpec("commodity_tag", "Commodity Tag", kind=FieldKind.LIST, levels=_ADV,
              aliases=("commodity", "commodity tags", "tags", "hs code", "commodity code")),
    FieldSpec("country_of_origin", "Country of Origin", kind=FieldKind.STRING, levels=_ADV,
              aliases=("country", "origin", "coo", "made in")),
    FieldSpec("safety_stock", "Safety Stock", kind=FieldKind.INTEGER, levels=_ADV,
              aliases=("buffer stock", "safety")),
    FieldSpec("lead_time_days", "Lead Time (Days)", kind=FieldKind.INTEGER, levels=_ADV,
              aliases=("lead time", "leadtime", "lt days", "lead time days")),
    FieldSpec("criticality", "Criticality", kind=FieldKind.ENUM, levels=_ADV,
              choices=("low", "medium", "high", "critical"),
              aliases=("priority", "importance")),
    FieldSpec("strategic_item", "Strategic Item", kind=FieldKind.BOOL, levels=_ADV,
              aliases=("strategic",)),
    FieldSpec("alternate_supplier_available", "Alternate Supplier Available", kind=FieldKind.BOOL, levels=_ADV,
              aliases=("alternate supplier", "alt supplier", "second source", "dual source")),
    FieldSpec("status", "Status", kind=FieldKind.ENUM, levels=_ADV,
              choices=("active", "inactive", "discontinued"),
              aliases=("state",)),
)

# clean-field -> Product column. Only keys present in the validated row are applied.
_PRODUCT_ATTRS = {
    "name": "name",
    "description": "description",
    "barcode": "barcode",
    "cost_price": "cost_price",
    "selling_price": "selling_price",
    "unit_of_measure": "unit_of_measure",
    "reorder_point": "reorder_point",
    "safety_stock": "safety_stock",
    "lead_time_days": "lead_time_days",
    "commodity_tag": "commodity_tags",
    "country_of_origin": "country_of_origin",
    "criticality": "criticality",
    "strategic_item": "strategic_item",
    "alternate_supplier_available": "alternate_supplier_available",
    "status": "status",
}


def _currency(raw: Any) -> str | None:
    s = str(raw or "").strip().upper()
    return s if len(s) == 3 and s.isalpha() else None


class InventoryImporter(ResourceImporter):
    key = "inventory"
    label = "Inventory & Products"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    async def process_row(self, ctx: ImportRowContext, clean: dict[str, Any]) -> RowResult:
        sku = clean["sku"]

        # Warehouse first: if it can't be resolved (skip mode), do nothing else.
        warehouse = await ctx.resolve_warehouse(clean.get("warehouse"))
        if warehouse is None:
            return RowResult.skipped(
                f"warehouse '{clean.get('warehouse') or '(default)'}' not found and not created",
                sku=sku,
            )

        supplier = await ctx.resolve_supplier(clean.get("supplier"))
        category = await ctx.get_or_create_category(clean.get("category"))
        brand = await ctx.get_or_create_brand(clean.get("brand"))

        attrs: dict[str, Any] = {
            col: clean[fld] for fld, col in _PRODUCT_ATTRS.items() if fld in clean
        }
        cur = _currency(clean.get("currency"))
        if cur is not None:
            attrs["currency"] = cur

        product = await ctx.upsert_product(
            sku=sku, attrs=attrs, category=category, brand=brand, supplier=supplier
        )

        qty: Decimal = clean.get("quantity") or Decimal("0")
        if qty > 0:
            await ctx.set_initial_stock(
                product=product, warehouse=warehouse, qty=qty, unit_cost=clean.get("cost_price")
            )
        return RowResult.imported(sku=sku)


register(InventoryImporter())
