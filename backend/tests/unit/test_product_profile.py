"""Unit tests for the Product Intelligence Profile and its consumption seams."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.catalog.profile import ProductProfile, suggested_forecast_method, vulnerability
from app.intelligence.signals import build_snapshot, match_context

D = Decimal


def _row(category, scope_type, scope_key, severity, headline="h"):
    return SimpleNamespace(
        category=category, scope_type=scope_type, scope_key=scope_key,
        severity=D(severity), demand_factor=D("1"), confidence=D("0.9"), headline=headline,
    )


# ------------------------------ ProductProfile ------------------------------ #
def test_from_product_reads_attributes_and_maps_carton_dims():
    product = SimpleNamespace(
        commodity_tags=["steel", "copper"], country_of_origin="CN", transport_mode="sea",
        criticality="critical", supplier_dependency="single", demand_type="lumpy",
        substitutability="none", units_per_carton=12, moq=500, lead_time_days=45,
        volume_per_carton=D("0.08"), weight_per_carton=D("14.5"),
    )
    p = ProductProfile.from_product(product)
    assert p.commodity_tags == ("steel", "copper")
    assert p.country_of_origin == "CN"
    assert p.carton_volume_m3 == D("0.08")   # mapped from volume_per_carton
    assert p.carton_weight_kg == D("14.5")   # mapped from weight_per_carton
    assert p.units_per_carton == 12 and p.moq == 500 and p.lead_time_days == 45


def test_from_product_defaults_when_attrs_absent():
    # A bare object (e.g. older row) gets safe defaults — identity behaviour.
    p = ProductProfile.from_product(SimpleNamespace(units_per_carton=1))
    assert p.commodity_tags == ()
    assert p.criticality == "medium"
    assert p.country_of_origin is None
    amp, drivers = vulnerability(p)
    assert amp == D("1.0000") and drivers == []  # no amplification for a plain product


# ------------------------------ vulnerability ------------------------------- #
def test_vulnerability_amplifies_for_critical_single_sourced_unsubstitutable():
    p = ProductProfile(criticality="critical", supplier_dependency="single", substitutability="none")
    amp, drivers = vulnerability(p)
    # 1 + 0.30 (critical) + 0.15 (single) + 0.20 (none) = 1.65
    assert amp == D("1.6500")
    assert "criticality=critical" in drivers
    assert "sourcing=single" in drivers


def test_vulnerability_high_substitutability_reduces_risk():
    p = ProductProfile(criticality="low", substitutability="high")
    amp, _ = vulnerability(p)
    assert amp == D("0.9500")  # 1 - 0.05


def test_vulnerability_strategic_item_raises_and_alternate_supplier_mitigates():
    p = ProductProfile(strategic_item=True, alternate_supplier_available=True)
    amp, drivers = vulnerability(p)
    assert amp == D("1.0500")  # 1 + 0.15 (strategic) - 0.10 (alternate supplier)
    assert "strategic_item" in drivers
    assert "alternate_supplier_available" in drivers


def test_vulnerability_is_clamped():
    p = ProductProfile(criticality="critical", supplier_dependency="single", substitutability="none")
    # already 1.65 (within band); confirm it never exceeds the cap with stacking
    amp, _ = vulnerability(p)
    assert amp <= D("1.75")


# -------------------------- forecast method mapping ------------------------- #
def test_suggested_forecast_method_maps_demand_character():
    assert suggested_forecast_method("smooth") == "moving_average"
    assert suggested_forecast_method("erratic") == "exponential_smoothing"
    assert suggested_forecast_method("intermittent") == "croston"
    assert suggested_forecast_method("lumpy") == "croston"
    assert suggested_forecast_method("seasonal") == "seasonal"
    assert suggested_forecast_method(None) is None


# --------------------- intelligence matching by product --------------------- #
def test_build_snapshot_groups_commodity_scope():
    snap = build_snapshot([_row("commodity", "commodity", "steel", "0.4", "Steel +30%")])
    assert "steel" in snap.by_commodity
    assert not snap.is_empty


def test_match_context_binds_commodity_and_origin_to_product():
    snap = build_snapshot(
        [
            _row("commodity", "commodity", "steel", "0.4", "Steel +30%"),
            _row("trade", "country", "CN", "0.3", "Tariff on CN"),
            _row("supplier", "supplier", "sup-1", "0.5", "Supplier risk"),
        ],
        supplier_country={},
    )
    # A product made of steel, shipped from CN, with no matching supplier signal
    matched = match_context(snap, supplier_id=None, commodity_tags=("steel",), origin_country="CN")
    headlines = {a.headline for a in matched}
    assert headlines == {"Steel +30%", "Tariff on CN"}  # both reached the product


def test_match_context_deduplicates_overlapping_axes():
    # supplier's country and the product origin are both CN -> count the signal once
    snap = build_snapshot(
        [_row("freight", "country", "CN", "0.5", "Freight ex-CN")],
        supplier_country={"sup-1": "CN"},
    )
    matched = match_context(snap, supplier_id="sup-1", origin_country="CN")
    assert len(matched) == 1
