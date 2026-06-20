"""Automatic column detection: match a spreadsheet's header row to field specs by
normalized alias. Pure (stdlib only)."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from app.imports.domain.fields import FieldSpec

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(header: str | None) -> str:
    """Lowercase and strip every non-alphanumeric character so 'Part No.',
    'part_no' and 'PART NO' all collapse to 'partno'."""
    return _NON_ALNUM.sub("", (header or "").strip().lower())


def detect_columns(
    headers: Sequence[str], fields: Iterable[FieldSpec]
) -> dict[str, int | None]:
    """Return ``{field_name: header_index | None}``. Each header column is claimed by
    at most one field (first match wins, in field order), so a dedicated 'Description'
    column won't be stolen by another field that also lists it as an alias."""
    norm_headers = [normalize(h) for h in headers]
    mapping: dict[str, int | None] = {}
    claimed: set[int] = set()
    for spec in fields:
        candidates = {normalize(spec.name), normalize(spec.label)}
        candidates.update(normalize(a) for a in spec.aliases)
        candidates.discard("")
        match: int | None = None
        for i, nh in enumerate(norm_headers):
            if i in claimed or not nh:
                continue
            if nh in candidates:
                match = i
                claimed.add(i)
                break
        mapping[spec.name] = match
    return mapping


def header_signature(headers: Sequence[str]) -> str:
    """A stable fingerprint of a header row (order + normalized text). A saved
    mapping is keyed by this, so it's only reused for an identical layout — which
    keeps the stored column indices valid."""
    return hashlib.sha256("|".join(normalize(h) for h in headers).encode("utf-8")).hexdigest()


def merge_mapping(detected: dict[str, int | None], saved: dict[str, int | None]) -> dict[str, int | None]:
    """Overlay a saved mapping on top of auto-detection (saved wins where set)."""
    merged = dict(detected)
    for field, idx in saved.items():
        if field in merged:
            merged[field] = idx
    return merged
