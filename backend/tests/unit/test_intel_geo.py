"""Country normalisation + that it makes country signals match suppliers."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.intelligence.domain.geo import to_iso2
from app.intelligence.signals import build_snapshot, match_context


def test_to_iso2_normalizes_common_forms():
    assert to_iso2("USA") == "US"
    assert to_iso2("United States") == "US"
    assert to_iso2("china") == "CN"
    assert to_iso2("CN") == "CN"
    assert to_iso2("CHN") == "CN"
    assert to_iso2("Türkiye") == "TR"
    assert to_iso2("UK") == "GB"
    assert to_iso2(None) is None
    assert to_iso2("") is None
    assert to_iso2("Atlantis") is None     # unknown -> no match (prior behaviour)


def _country_signal(scope_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        category="geopolitical", scope_type="country", scope_key=scope_key,
        severity=Decimal("0.8"), demand_factor=Decimal("1"), confidence=Decimal("0.7"),
        headline=f"risk in {scope_key}",
    )


def test_free_text_supplier_country_matches_iso2_signal():
    # The whole point: a supplier stored as "USA" now matches a "US" signal.
    sid = "supplier-1"
    snap = build_snapshot([_country_signal("US")], supplier_country={sid: "USA"})
    matched = match_context(snap, sid, include_global=False)
    assert len(matched) == 1
    assert matched[0].headline == "risk in US"


def test_origin_country_name_matches_iso2_signal():
    snap = build_snapshot([_country_signal("CN")], supplier_country={})
    matched = match_context(snap, None, origin_country="China", include_global=False)
    assert len(matched) == 1


def test_unmappable_country_still_no_match():
    sid = "s2"
    snap = build_snapshot([_country_signal("US")], supplier_country={sid: "Atlantis"})
    assert match_context(snap, sid, include_global=False) == []
