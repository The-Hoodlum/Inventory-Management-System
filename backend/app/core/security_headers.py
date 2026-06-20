"""Security response headers (pure; unit-testable)."""
from __future__ import annotations


def build_security_headers(*, hsts_enabled: bool, hsts_max_age: int) -> dict[str, str]:
    """Baseline hardening headers applied to every response. HSTS is only
    emitted when enabled (i.e. when served over HTTPS), to avoid pinning
    plain-HTTP dev origins."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        # Modern guidance: disable the legacy auditor rather than enable it.
        "X-XSS-Protection": "0",
    }
    if hsts_enabled:
        headers["Strict-Transport-Security"] = f"max-age={hsts_max_age}; includeSubDomains"
    return headers
