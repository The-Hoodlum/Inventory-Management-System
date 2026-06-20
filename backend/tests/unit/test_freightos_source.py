"""Unit tests for the Freightos external source, credential gating, and auth.

No secrets, no network: gating tests confirm the source is inert without BOTH
credentials (returns [] before any HTTP); auth tests check header construction;
the parser is tested against a sample response shape (a unit fixture, not data
injected into the platform).
"""
from __future__ import annotations

import base64
from decimal import Decimal
from types import SimpleNamespace

from app.intelligence.providers.base import NullSource
from app.intelligence.sources.factory import build_external_source
from app.intelligence.sources.freightos import FreightosSource, credential_problems

D = Decimal


# --------------------------- credential_problems ---------------------------- #
def test_credential_problems_disabled_is_clean():
    assert credential_problems(enabled=False, api_key=None, api_secret=None) == []


def test_credential_problems_flags_each_missing_field_by_name_only():
    assert credential_problems(enabled=True, api_key=None, api_secret=None) == [
        "FREIGHTOS_API_KEY", "FREIGHTOS_API_SECRET",
    ]
    assert credential_problems(enabled=True, api_key="k", api_secret=None) == ["FREIGHTOS_API_SECRET"]
    assert credential_problems(enabled=True, api_key=None, api_secret="s") == ["FREIGHTOS_API_KEY"]
    assert credential_problems(enabled=True, api_key="k", api_secret="s") == []


# -------------------------------- gating ------------------------------------ #
async def test_inert_without_both_credentials_returns_empty():
    assert await FreightosSource(api_key=None, api_secret=None).fetch("freight", []) == []
    assert await FreightosSource(api_key="k", api_secret=None).fetch("freight", []) == []
    assert await FreightosSource(api_key=None, api_secret="s").fetch("freight", []) == []


async def test_ignores_non_freight_categories():
    src = FreightosSource(api_key="k", api_secret="s")
    assert await src.fetch("commodity", []) == []
    assert await src.fetch("port", ["X"]) == []


# -------------------------------- auth -------------------------------------- #
def test_basic_header_encodes_key_and_secret():
    header = FreightosSource._basic_header("mykey", "mysecret")
    expected = base64.b64encode(b"mykey:mysecret").decode()
    assert header == {"Authorization": f"Basic {expected}"}


def test_header_pair_mode():
    assert FreightosSource._header_pair("k", "s") == {"x-api-key": "k", "x-api-secret": "s"}


def test_repr_never_exposes_credentials():
    src = FreightosSource(api_key="SUPER_SECRET_KEY", api_secret="SUPER_SECRET_VALUE")
    text = repr(src)
    assert "SUPER_SECRET_KEY" not in text
    assert "SUPER_SECRET_VALUE" not in text
    assert "configured=True" in text


# -------------------------------- parser ------------------------------------ #
def test_parse_maps_lanes_to_origin_country():
    src = FreightosSource(api_key="k", api_secret="s")
    payload = {"indices": [{"lane": "CNSHA-USLAX", "value": 2450, "change_pct": 0.18, "trend": "up"}]}
    metrics = src._parse(payload)
    assert len(metrics) == 1
    assert metrics[0].key == "CN"
    assert metrics[0].value == D("2450")
    assert metrics[0].pct_change == D("0.18")
    assert metrics[0].detail == {"lane": "CNSHA-USLAX"}


def test_parse_skips_unrecognised_shapes():
    src = FreightosSource(api_key="k", api_secret="s")
    assert src._parse("nonsense") == []
    assert src._parse({"unexpected": 1}) == []


# -------------------------------- factory ----------------------------------- #
def _settings(*, configured: bool):
    return SimpleNamespace(
        freightos_configured=configured,
        freightos_api_key="k" if configured else None,
        freightos_api_secret="s" if configured else None,
        freightos_base_url="https://api.freightos.com",
        freightos_index_path="/api/v2/indices",
        freightos_auth_mode="basic",
        freightos_token_url="https://api.freightos.com/oauth/token",
        freightos_timeout_seconds=20.0,
        freightos_lanes=["CNSHA-USLAX"],
    )


def test_factory_returns_freightos_when_configured():
    src = build_external_source(_settings(configured=True))
    assert isinstance(src, FreightosSource)
    assert src.configured is True


def test_factory_returns_null_source_when_not_configured():
    assert isinstance(build_external_source(_settings(configured=False)), NullSource)
