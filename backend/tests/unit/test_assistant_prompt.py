"""The system prompt is generated dynamically from tenant config (industry-agnostic)."""
from __future__ import annotations

import datetime as dt

from app.assistant.domain.prompt import ASSISTANT_RULES, TenantConfig, build_system_prompt

TODAY = dt.date(2026, 6, 21)


def test_prompt_reflects_tenant_identity_and_currency():
    cfg = TenantConfig(
        company_name="TVS Zambia", industry="Motorcycles and Spare Parts", currency="ZMW",
        assistant_name="TVS Zambia Assistant",
        assistant_prompt="Be concise and helpful for branch staff.",
    )
    p = build_system_prompt(cfg, TODAY)
    assert "TVS Zambia Assistant" in p
    assert "TVS Zambia" in p
    assert "Motorcycles and Spare Parts" in p
    assert "ZMW" in p
    assert "Be concise and helpful for branch staff." in p
    assert "2026-06-21" in p


def test_same_engine_different_tenants():
    foods = build_system_prompt(
        TenantConfig(company_name="ABC Foods", industry="Food Distribution", currency="USD"), TODAY)
    hardware = build_system_prompt(
        TenantConfig(company_name="XYZ Hardware", industry="Construction Materials", currency="ZAR"), TODAY)
    assert "ABC Foods" in foods and "Food Distribution" in foods and "USD" in foods
    assert "XYZ Hardware" in hardware and "Construction Materials" in hardware and "ZAR" in hardware
    # No cross-contamination and no hard-coded business identity.
    assert "ABC Foods" not in hardware
    for term in ("motorcycle", "tvs", "zambia", "zmw"):
        assert term not in hardware.lower()


def test_generic_rules_have_no_business_specifics():
    blob = ASSISTANT_RULES.lower()
    for term in ("motorcycle", "tvs", "zambia", "zmw", "lusaka", "ndola", "solwezi", "spare part"):
        assert term not in blob


def test_prompt_degrades_without_config():
    p = build_system_prompt(TenantConfig(), TODAY)  # all defaults
    assert "inventory assistant" in p.lower()
    assert "USD" in p  # default currency
