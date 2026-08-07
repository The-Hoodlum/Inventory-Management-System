"""Per-cell coercion + validation, shared by preview and import so both judge rows
identically. Pure (stdlib only). Returns typed values or human-readable errors."""
from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from app.imports.domain.fields import FieldKind, FieldSpec

# Currency symbols/spaces to drop anywhere in a numeric cell, and currency codes/letters
# to drop at either end. Sheets are often exported for humans: "$17.27", "345.4 K"
# (K = Zambian Kwacha, a suffix, NOT thousands), "ZMW 1,029.60". We strip the decoration
# and parse the bare number. Bare numbers are unaffected, so nothing that parsed before
# changes meaning.
_NUM_DECORATION = re.compile(r"[$£€\s]")
_NUM_CURRENCY_CODE = re.compile(r"(?i)^(k|zmw|usd)|(k|zmw|usd)$")


def _clean_number(s: str) -> str:
    t = _NUM_DECORATION.sub("", s.replace(",", ""))  # drop symbols, spaces, thousands sep
    return _NUM_CURRENCY_CODE.sub("", t)              # drop a leading/trailing K/ZMW/USD


def coerce(spec: FieldSpec, raw: Any) -> tuple[Any, str | None]:
    """Coerce one raw cell for ``spec``. Returns ``(value, error)``; exactly one is
    meaningful. An empty optional field yields ``(None, None)``."""
    s = "" if raw is None else str(raw).strip()

    if s == "":
        if spec.required:
            return None, f"{spec.label} is required"
        return None, None

    if spec.kind is FieldKind.STRING:
        return s, None

    if spec.kind is FieldKind.ENUM:
        for c in spec.choices:
            if c.lower() == s.lower():
                return c, None
        return None, f"{spec.label} '{s}' must be one of: {', '.join(spec.choices)}"

    if spec.kind is FieldKind.LIST:
        return [t.strip() for t in s.split(",") if t.strip()], None

    if spec.kind is FieldKind.BOOL:
        low = s.lower()
        if low in ("yes", "y", "true", "t", "1"):
            return True, None
        if low in ("no", "n", "false", "f", "0"):
            return False, None
        return None, f"{spec.label} '{s}' must be yes/no"

    if spec.kind in (FieldKind.INTEGER, FieldKind.DECIMAL):
        try:
            d = Decimal(_clean_number(s))  # tolerate thousands sep + currency decoration
        except (InvalidOperation, ValueError):
            return None, f"{spec.label} '{s}' is not a valid number"
        if d < 0 and not spec.signed:
            return None, f"{spec.label} cannot be negative"
        if spec.kind is FieldKind.INTEGER:
            if d != d.to_integral_value():
                return None, f"{spec.label} '{s}' must be a whole number"
            return int(d), None
        return d, None

    return s, None


def validate_mapped(
    fields: Iterable[FieldSpec], raw_by_field: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Validate a row already keyed by field name. Returns ``(clean, errors)`` where
    ``clean`` holds the coerced values for fields that passed."""
    clean: dict[str, Any] = {}
    errors: list[str] = []
    for spec in fields:
        value, err = coerce(spec, raw_by_field.get(spec.name))
        if err:
            errors.append(err)
        elif value is not None:
            clean[spec.name] = value
    return clean, errors
