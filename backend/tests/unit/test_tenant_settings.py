"""Tenant settings mapping: company_name<->name, default_currency<->base_currency."""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.tenant import TenantSettingsOut, TenantSettingsUpdate


def test_out_maps_from_tenant_columns():
    t = SimpleNamespace(
        name="ABC Foods", brand_name="ABC", industry="Food Distribution", base_currency="USD",
        country="US", timezone="America/New_York", logo_url=None,
        assistant_name="ABC Assistant", assistant_prompt="Be brief.", feature_flags={"alerts": True},
    )
    out = TenantSettingsOut.from_tenant(t)
    assert out.company_name == "ABC Foods"        # <- name
    assert out.default_currency == "USD"          # <- base_currency
    assert out.industry == "Food Distribution"
    assert out.feature_flags == {"alerts": True}


def test_update_maps_only_set_fields_to_columns():
    upd = TenantSettingsUpdate(company_name="XYZ Hardware", default_currency="zar", industry="Construction")
    cols = upd.to_columns()
    assert cols == {"name": "XYZ Hardware", "base_currency": "ZAR", "industry": "Construction"}
    # unset fields are not included
    assert "brand_name" not in cols and "timezone" not in cols


def test_update_empty_is_noop():
    assert TenantSettingsUpdate().to_columns() == {}
