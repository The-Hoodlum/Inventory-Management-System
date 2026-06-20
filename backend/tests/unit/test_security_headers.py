"""Unit tests for the security-headers builder (pure)."""
from __future__ import annotations

from app.core.security_headers import build_security_headers


def test_baseline_headers_present_without_hsts():
    h = build_security_headers(hsts_enabled=False, hsts_max_age=31536000)
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "Strict-Transport-Security" not in h


def test_hsts_included_when_enabled():
    h = build_security_headers(hsts_enabled=True, hsts_max_age=12345)
    assert h["Strict-Transport-Security"] == "max-age=12345; includeSubDomains"
