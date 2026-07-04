"""Unit tests for the motorcycle_units import target's pure helpers."""
from __future__ import annotations

import datetime as dt

from app.imports.domain.registry import get_importer
from app.imports.targets.motorcycle_units import _STATUS_MAP, _parse_date


def test_parse_date_accepts_common_formats():
    assert _parse_date("2026-07-02") == (dt.date(2026, 7, 2), True)
    assert _parse_date("02/07/2026") == (dt.date(2026, 7, 2), True)  # d/m/Y
    assert _parse_date("2026-07-02T10:30:00") == (dt.date(2026, 7, 2), True)  # trailing time tolerated
    assert _parse_date("") == (None, True)      # empty optional -> ok
    assert _parse_date(None) == (None, True)


def test_parse_date_rejects_garbage():
    value, ok = _parse_date("not-a-date")
    assert value is None and ok is False


def test_status_map_covers_the_sheet_vocabulary():
    assert set(_STATUS_MAP) == {"unassembled", "assembled", "reserved", "sold"}
    # Maps each sheet value to one of the five sale statuses.
    assert _STATUS_MAP["unassembled"] == "unassembled"
    assert _STATUS_MAP["sold"] == "sold"


def test_importer_is_registered_and_atomic():
    imp = get_importer("motorcycle_units")
    assert getattr(imp, "atomic", False) is True
    assert imp.key_field == "chassis_number"
    names = {f.name for f in imp.fields}
    assert {"chassis_number", "model", "branch", "status"}.issubset(names)
    # required set matches the spec
    required = {f.name for f in imp.fields if f.required}
    assert required == {"chassis_number", "model", "branch", "status"}


def test_basic_template_has_the_key_columns():
    imp = get_importer("motorcycle_units")
    basic = imp.template_columns("basic")
    assert "Chassis Number" in basic and "Model" in basic and "Branch" in basic and "Status" in basic
