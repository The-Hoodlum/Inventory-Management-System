"""Unit tests for the opening_balances import target's pure helpers + registration."""
from __future__ import annotations

import datetime as dt

from app.imports.domain.registry import get_importer
from app.imports.targets.opening_balances import _parse_date


def test_parse_date_requires_a_valid_date():
    assert _parse_date("2026-07-01") == (dt.date(2026, 7, 1), True)
    assert _parse_date("01/07/2026") == (dt.date(2026, 7, 1), True)  # d/m/Y
    assert _parse_date("2026-07-01T00:00:00") == (dt.date(2026, 7, 1), True)  # trailing time tolerated
    # required here: empty / None / garbage are NOT ok
    assert _parse_date("") == (None, False)
    assert _parse_date(None) == (None, False)
    assert _parse_date("not-a-date") == (None, False)


def test_importer_is_registered_and_atomic():
    imp = get_importer("opening_balances")
    assert getattr(imp, "atomic", False) is True
    assert imp.key_field == "product"
    names = {f.name for f in imp.fields}
    assert {"product", "warehouse", "opening_qty", "as_of_date"}.issubset(names)
    # required set matches the spec (branch is an optional cross-check)
    required = {f.name for f in imp.fields if f.required}
    assert required == {"product", "warehouse", "opening_qty", "as_of_date"}


def test_basic_template_has_the_key_columns():
    imp = get_importer("opening_balances")
    basic = imp.template_columns("basic")
    assert "Product" in basic and "Warehouse" in basic
    assert "Opening Quantity" in basic and "As-of Date" in basic
