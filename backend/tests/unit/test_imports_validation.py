"""Per-cell coercion + row validation."""
from __future__ import annotations

from decimal import Decimal

from app.imports.domain.fields import FieldKind, FieldSpec
from app.imports.domain.validation import coerce, validate_mapped

SKU = FieldSpec("sku", "SKU", required=True, kind=FieldKind.STRING)
QTY = FieldSpec("quantity", "Quantity On Hand", required=True, kind=FieldKind.DECIMAL)
ROP = FieldSpec("reorder_point", "Reorder Point", kind=FieldKind.INTEGER)
STATUS = FieldSpec("status", "Status", kind=FieldKind.ENUM, choices=("active", "inactive", "discontinued"))
TAGS = FieldSpec("commodity_tag", "Commodity Tag", kind=FieldKind.LIST)


def test_required_empty_is_error():
    val, err = coerce(SKU, "")
    assert val is None and "required" in err


def test_optional_empty_is_silent():
    assert coerce(ROP, "") == (None, None)


def test_decimal_parses_and_strips_thousands():
    assert coerce(QTY, "1,250.5") == (Decimal("1250.5"), None)


def test_negative_number_rejected():
    val, err = coerce(QTY, "-5")
    assert val is None and "negative" in err


def test_non_numeric_rejected():
    val, err = coerce(QTY, "abc")
    assert val is None and "not a valid number" in err


def test_integer_must_be_whole():
    val, err = coerce(ROP, "3.5")
    assert val is None and "whole number" in err
    assert coerce(ROP, "10") == (10, None)


def test_enum_case_insensitive_and_invalid():
    assert coerce(STATUS, "Active") == ("active", None)
    val, err = coerce(STATUS, "frozen")
    assert val is None and "must be one of" in err


def test_list_splits_on_comma():
    val, err = coerce(TAGS, "steel, copper ,, alloy")
    assert err is None and val == ["steel", "copper", "alloy"]


def test_bool_accepts_yes_no_variants():
    flag = FieldSpec("strategic_item", "Strategic Item", kind=FieldKind.BOOL)
    assert coerce(flag, "Yes") == (True, None)
    assert coerce(flag, "y") == (True, None)
    assert coerce(flag, "1") == (True, None)
    assert coerce(flag, "no") == (False, None)
    assert coerce(flag, "FALSE") == (False, None)
    val, err = coerce(flag, "maybe")
    assert val is None and "yes/no" in err
    assert coerce(flag, "") == (None, None)  # optional + empty


def test_validate_mapped_collects_errors_and_clean():
    fields = [SKU, QTY, ROP]
    clean, errors = validate_mapped(fields, {"sku": "A-1", "quantity": "10", "reorder_point": "x"})
    assert clean["sku"] == "A-1"
    assert clean["quantity"] == Decimal("10")
    assert "reorder_point" not in clean
    assert any("Reorder Point" in e for e in errors)
