"""Column auto-detection: normalized alias matching, incl. the spec examples."""
from __future__ import annotations

import app.imports.targets  # noqa: F401  (registers the inventory target)
from app.imports.domain.detection import (
    detect_columns,
    header_signature,
    merge_mapping,
    normalize,
)
from app.imports.domain.registry import get_importer

FIELDS = get_importer("inventory").fields


def test_normalize_collapses_punctuation_and_case():
    assert normalize("Part No.") == "partno"
    assert normalize("  QTY_Available ") == "qtyavailable"
    assert normalize("On Hand") == "onhand"


def test_detects_part_no_product_name_qty_available():
    mapping = detect_columns(["Part No", "Product Name", "Qty Available"], FIELDS)
    assert mapping["sku"] == 0
    assert mapping["name"] == 1
    assert mapping["quantity"] == 2


def test_detects_item_code_item_name_stock():
    mapping = detect_columns(["Item Code", "Item Name", "Stock"], FIELDS)
    assert mapping["sku"] == 0
    assert mapping["name"] == 1
    assert mapping["quantity"] == 2


def test_dedicated_description_column_not_stolen_by_name():
    # A sheet with SKU/Description/On Hand: Description binds to the description
    # field, not name (name stays unmapped for the user to map manually).
    mapping = detect_columns(["SKU", "Description", "On Hand"], FIELDS)
    assert mapping["sku"] == 0
    assert mapping["description"] == 1
    assert mapping["quantity"] == 2
    assert mapping["name"] is None


def test_each_header_claimed_once():
    mapping = detect_columns(["SKU", "Name", "Qty", "Warehouse", "Supplier"], FIELDS)
    assigned = [i for i in mapping.values() if i is not None]
    assert len(assigned) == len(set(assigned))  # no header used twice
    assert mapping["warehouse"] == 3
    assert mapping["supplier"] == 4


def test_unknown_headers_map_to_none():
    mapping = detect_columns(["Foo", "Bar"], FIELDS)
    assert mapping["sku"] is None
    assert mapping["quantity"] is None


def test_header_signature_stable_and_layout_sensitive():
    # Same headers (different case/punctuation) -> same signature.
    assert header_signature(["SKU", "Qty"]) == header_signature(["sku", "qty."])
    # Different order -> different signature (column indices would differ).
    assert header_signature(["SKU", "Qty"]) != header_signature(["Qty", "SKU"])


def test_merge_mapping_saved_overrides_detected():
    detected = {"sku": 0, "name": 1, "quantity": None}
    saved = {"quantity": 2, "name": 5}
    merged = merge_mapping(detected, saved)
    assert merged == {"sku": 0, "name": 5, "quantity": 2}
