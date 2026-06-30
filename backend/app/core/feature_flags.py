"""Canonical per-tenant feature flags (industry-agnostic module toggles).

The set of modules a tenant can switch on/off lives here, with defaults. Stored values
(``tenants.feature_flags`` JSONB) are overlaid on the defaults at read time, so adding a
new flag here doesn't require touching existing tenants. ``is_enabled`` is the single
check call sites use to gate optional modules.
"""
from __future__ import annotations

# key -> (human label, default-enabled)
FEATURE_FLAGS: dict[str, tuple[str, bool]] = {
    "inventory": ("Inventory", True),
    "purchase_orders": ("Purchase Orders", True),
    "order_requests": ("Order Requests", True),
    "reorder_engine": ("Reorder Engine", True),
    "forecasting": ("Forecasting", True),
    "supply_chain_intelligence": ("Supply Chain Intelligence", True),
    "whatsapp_assistant": ("WhatsApp Assistant", True),
    "multi_warehouse": ("Multi-Warehouse", True),
    "barcode_scanning": ("Barcode Scanning", False),
    "sales_orders": ("Sales & Distribution", False),
    "pos": ("Point of Sale", False),
    "manufacturing": ("Manufacturing", False),
    "expiry_tracking": ("Expiry Tracking", False),
}

DEFAULTS: dict[str, bool] = {key: default for key, (_label, default) in FEATURE_FLAGS.items()}


def merged_flags(stored: dict | None) -> dict[str, bool]:
    """All known flags with their defaults, overlaid with the tenant's stored values
    (unknown keys ignored)."""
    out = dict(DEFAULTS)
    for key, value in (stored or {}).items():
        if key in FEATURE_FLAGS:
            out[key] = bool(value)
    return out


def sanitize(stored: dict | None) -> dict[str, bool]:
    """Keep only known flag keys, coerced to bool — for persisting an update."""
    return {key: bool(value) for key, value in (stored or {}).items() if key in FEATURE_FLAGS}


def is_enabled(stored: dict | None, key: str) -> bool:
    """Whether a module is on for this tenant (defaults apply when unset)."""
    return merged_flags(stored).get(key, False)
