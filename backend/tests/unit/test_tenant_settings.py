"""Tenant settings mapping: company_name<->name, default_currency<->base_currency,
branding colors, and feature flags (merged with defaults on read, sanitized on write)."""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.tenant import TenantSettingsOut, TenantSettingsUpdate


def test_out_maps_from_tenant_columns():
    t = SimpleNamespace(
        name="ABC Foods", brand_name="ABC", industry="Food Distribution", base_currency="USD",
        country="US", timezone="America/New_York", logo_url=None,
        branding_colors={"primary": "#0a7"},
        assistant_name="ABC Assistant", assistant_prompt="Be brief.",
        feature_flags={"manufacturing": True},
    )
    out = TenantSettingsOut.from_tenant(t)
    assert out.company_name == "ABC Foods"        # <- name
    assert out.default_currency == "USD"          # <- base_currency
    assert out.industry == "Food Distribution"
    assert out.branding_colors == {"primary": "#0a7"}
    # feature_flags merged with defaults (stored override applied, defaults filled in)
    assert out.feature_flags["manufacturing"] is True
    assert out.feature_flags["inventory"] is True  # default


def test_update_maps_only_set_fields_to_columns():
    upd = TenantSettingsUpdate(company_name="XYZ Hardware", default_currency="zar", industry="Construction")
    cols = upd.to_columns()
    assert cols == {"name": "XYZ Hardware", "base_currency": "ZAR", "industry": "Construction"}
    # unset fields are not included
    assert "brand_name" not in cols and "timezone" not in cols


def test_update_sanitizes_feature_flags():
    upd = TenantSettingsUpdate(feature_flags={"manufacturing": True, "bogus": True, "inventory": 0})
    cols = upd.to_columns()
    assert cols["feature_flags"] == {"manufacturing": True, "inventory": False}  # known keys only, bool-coerced


def test_update_empty_is_noop():
    assert TenantSettingsUpdate().to_columns() == {}
