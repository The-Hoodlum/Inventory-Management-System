"""Unit tests for the motorcycle_units import target's pure helpers."""
from __future__ import annotations

import datetime as dt

from app.imports.domain.registry import get_importer
from app.imports.targets.motorcycle_units import (
    FIVE_STATUSES,
    _parse_date,
    guess_status,
    split_consignment,
)


def test_parse_date_accepts_common_formats():
    assert _parse_date("2026-07-02") == (dt.date(2026, 7, 2), True)
    assert _parse_date("02/07/2026") == (dt.date(2026, 7, 2), True)  # d/m/Y
    assert _parse_date("2026-07-02T10:30:00") == (dt.date(2026, 7, 2), True)  # trailing time tolerated
    assert _parse_date("") == (None, True)      # empty optional -> ok
    assert _parse_date(None) == (None, True)


def test_parse_date_rejects_garbage():
    value, ok = _parse_date("not-a-date")
    assert value is None and ok is False


def test_five_statuses_are_the_lifecycle_values():
    assert set(FIVE_STATUSES) == {"unassembled", "assembled", "reserved", "on_hold", "sold"}


def test_guess_status_suggests_a_mapping_for_typo_wordings():
    assert guess_status("Assembly Required") == "unassembled"
    assert guess_status("On Hold - cracked mudguard") == "on_hold"
    assert guess_status("Reserved (deposit paid)") == "reserved"
    assert guess_status("SOLD") == "sold"
    assert guess_status("Ready for showroom") == "assembled"
    assert guess_status("") is None
    assert guess_status("wat") is None


def test_split_consignment_peels_a_batch_token_off_a_known_base_model():
    existing = {"hlx 150", "rtr 180"}
    assert split_consignment("HLX 150 CONGO", existing) == ("HLX 150", "CONGO")
    assert split_consignment("RTR 180 KENYA 2026", existing) == ("RTR 180", "KENYA 2026")
    # An exact model (no trailing token) or an unknown base does not split.
    assert split_consignment("HLX 150", existing) is None
    assert split_consignment("APACHE 200 CONGO", existing) is None


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
