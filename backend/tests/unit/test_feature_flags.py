"""Per-tenant feature flags (pure)."""
from __future__ import annotations

from app.core.feature_flags import DEFAULTS, is_enabled, merged_flags, sanitize


def test_merged_defaults_when_unset():
    assert merged_flags(None) == DEFAULTS
    assert merged_flags({}) == DEFAULTS
    assert DEFAULTS["inventory"] is True
    assert DEFAULTS["manufacturing"] is False


def test_stored_overrides_defaults():
    flags = merged_flags({"manufacturing": True, "order_requests": False})
    assert flags["manufacturing"] is True
    assert flags["order_requests"] is False
    assert flags["inventory"] is True  # untouched default


def test_unknown_keys_ignored():
    assert "made_up" not in merged_flags({"made_up": True})
    assert sanitize({"made_up": True, "inventory": 1}) == {"inventory": True}


def test_is_enabled():
    assert is_enabled({"order_requests": True}, "order_requests") is True
    assert is_enabled({"order_requests": False}, "order_requests") is False
    assert is_enabled(None, "order_requests") is True   # default on
    assert is_enabled(None, "manufacturing") is False   # default off
