"""Unit tests for the free external intelligence providers + the registry.

Parsers are pure (no network); inert-by-default and registry gating are verified too.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.intelligence.providers.external import (
    ComtradeProvider,
    ExchangeRateHostProvider,
    GdeltProvider,
    ImfProvider,
    OpenWeatherProvider,
    WorldBankProvider,
)
from app.intelligence.providers.registry import build_free_providers

D = Decimal


# ---------------------------- ExchangeRate.host --------------------------- #
def test_exchangerate_parse_maps_currency_to_country_and_severity():
    payload = {
        "success": True, "base": "USD",
        "rates": {
            "CNY": {"start_rate": "7.0", "end_rate": "7.35", "change_pct": "5.0"},  # +5% -> sev 0.5
            "EUR": {"start_rate": "0.90", "end_rate": "0.909", "change_pct": "1.0"},  # +1% -> sev 0.1
            "ZZZ": {"change_pct": "50"},  # unknown currency -> dropped
        },
    }
    obs = {o.scope_key: o for o in ExchangeRateHostProvider(enabled=True, base_url="x").parse(payload)}
    assert set(obs) == {"CN", "DE"}
    assert obs["CN"].category == "trade" and obs["CN"].scope_type == "country"
    assert obs["CN"].severity == D("0.5")           # 0.05 / 0.10 cap
    assert obs["CN"].trend == "up"
    assert obs["DE"].severity == D("0.1")
    assert obs["CN"].source == "exchangerate_host"


def test_exchangerate_parse_handles_bad_shape():
    assert ExchangeRateHostProvider(enabled=True, base_url="x").parse({"rates": "nope"}) == []
    assert ExchangeRateHostProvider(enabled=True, base_url="x").parse(None) == []


# -------------------------------- World Bank ------------------------------ #
def test_worldbank_parse_scores_gdp_growth_risk():
    payload = [
        {"page": 1, "pages": 1, "total": 4},
        [
            {"country": {"id": "CN"}, "countryiso3code": "CHN", "date": "2024", "value": -12.0},  # (3-(-12))/15 = 1.0
            {"country": {"id": "TR"}, "countryiso3code": "TUR", "date": "2024", "value": 0.0},    # (3-0)/15 = 0.2
            {"country": {"id": "CH"}, "countryiso3code": "CHE", "date": "2024", "value": 5.0},    # healthy -> dropped
            {"country": {"id": "XX"}, "countryiso3code": "XXX", "date": "2024", "value": None},   # no value -> dropped
        ],
    ]
    obs = {o.scope_key: o for o in WorldBankProvider(enabled=True, base_url="y").parse(payload)}
    assert set(obs) == {"CN", "TR"}
    assert obs["CN"].category == "geopolitical"
    assert obs["CN"].severity == D("1")      # contraction -> max
    assert obs["TR"].severity == D("0.2")    # flat growth


def test_worldbank_parse_handles_bad_shape():
    assert WorldBankProvider(enabled=True, base_url="y").parse({"not": "a list"}) == []
    assert WorldBankProvider(enabled=True, base_url="y").parse([{"meta": 1}]) == []


# ----------------------------------- IMF ---------------------------------- #
def test_imf_parse_scores_inflation_latest_year():
    payload = {"values": {"PCPIPCH": {
        "CHN": {"2023": "1.0", "2024": "1.5"},   # latest 2024 -> 1.5/25 = 0.06
        "TUR": {"2024": "45.0"},                 # 45/25 -> clamp 1.0
        "ZZZ": {"2024": "5"},                    # not in ISO3 map -> dropped
    }}}
    obs = {o.scope_key: o for o in ImfProvider(enabled=True, base_url="z").parse(payload)}
    assert set(obs) == {"CN", "TR"}
    assert obs["CN"].severity == D("0.06") and obs["CN"].category == "trade"
    assert obs["TR"].severity == D("1")


# ---------------------------------- GDELT --------------------------------- #
def test_gdelt_parse_volume_to_global_severity():
    payload = {"timeline": [{"series": "Volume Intensity", "data": [
        {"date": "20260601", "value": 0.5}, {"date": "20260614", "value": 1.5},
    ]}]}
    obs = GdeltProvider(enabled=True, base_url="g").parse(payload)
    assert len(obs) == 1
    assert obs[0].scope_type == "global" and obs[0].category == "geopolitical"
    assert obs[0].severity == D("0.5")   # recent 1.5 / cap 3
    assert obs[0].trend == "up"


# -------------------------------- OpenWeather ----------------------------- #
def test_openweather_parse_flags_severe_and_skips_calm():
    payload = [
        {"city": "Shanghai", "country": "CN", "data": {"wind": {"speed": 30}, "weather": [{"main": "Thunderstorm"}]}},
        {"city": "Singapore", "country": "SG", "data": {"wind": {"speed": 2}, "weather": [{"main": "Clear"}]}},
    ]
    obs = {o.scope_key: o for o in OpenWeatherProvider(enabled=True, base_url="w", api_key="k").parse(payload)}
    assert set(obs) == {"CN"}            # calm Singapore dropped (< 0.15)
    assert obs["CN"].category == "port" and obs["CN"].severity == D("1")


# --------------------------------- Comtrade ------------------------------- #
def test_comtrade_parse_uses_yoy_change_for_severity():
    payload = {"data": [
        {"reporterCode": 156, "cmdCode": "72", "period": "2024", "primaryValue": 1000000, "pctChange": -30},
        {"reporterCode": 999, "cmdCode": "85", "period": "2024", "primaryValue": 5, "pctChange": 10},  # unknown M49 -> dropped
    ]}
    obs = {o.scope_key: o for o in ComtradeProvider(enabled=True, base_url="c", api_key="k").parse(payload)}
    assert set(obs) == {"CN"}
    assert obs["CN"].category == "trade"
    assert obs["CN"].severity == D("0.6")   # |−30|/100 / 0.5 cap
    assert obs["CN"].trend == "down"


# ------------------------------ inert default ----------------------------- #
async def test_disabled_provider_collects_nothing():
    p = ExchangeRateHostProvider(enabled=False, base_url="https://api.exchangerate.host")
    assert await p.collect() == []   # no network, no data


# -------------------------------- registry -------------------------------- #
def _settings(**over):
    base = dict(
        intel_http_timeout_seconds=20.0,
        intel_exchangerate_enabled=False, intel_exchangerate_base_url="https://api.exchangerate.host",
        intel_exchangerate_api_key=None,
        intel_worldbank_enabled=False, intel_worldbank_base_url="https://api.worldbank.org/v2",
        intel_imf_enabled=False, intel_imf_base_url="https://www.imf.org/external/datamapper/api/v1",
        intel_gdelt_enabled=False, intel_gdelt_base_url="https://api.gdeltproject.org/api/v2",
        intel_openweather_enabled=False, intel_openweather_base_url="https://api.openweathermap.org/data/2.5",
        intel_openweather_api_key=None,
        intel_comtrade_enabled=False, intel_comtrade_base_url="https://comtradeapi.un.org",
        intel_comtrade_api_key=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_registry_inert_by_default():
    assert build_free_providers(_settings()) == []


def test_registry_includes_only_enabled():
    providers = build_free_providers(_settings(intel_exchangerate_enabled=True, intel_worldbank_enabled=True))
    assert {p.key for p in providers} == {"exchangerate_host", "worldbank"}
    assert all(p.enabled for p in providers)


def test_registry_openweather_needs_key():
    # Enabled but no key -> not registered (avoids a guaranteed-failing call).
    assert build_free_providers(_settings(intel_openweather_enabled=True)) == []
    keyed = build_free_providers(_settings(intel_openweather_enabled=True, intel_openweather_api_key="k"))
    assert {p.key for p in keyed} == {"openweather"}


def test_registry_all_free_providers():
    providers = build_free_providers(_settings(
        intel_exchangerate_enabled=True, intel_worldbank_enabled=True, intel_imf_enabled=True,
        intel_gdelt_enabled=True, intel_openweather_enabled=True, intel_openweather_api_key="k",
        intel_comtrade_enabled=True, intel_comtrade_api_key="k",
    ))
    assert {p.key for p in providers} == {
        "exchangerate_host", "worldbank", "imf", "gdelt", "openweather", "comtrade",
    }
