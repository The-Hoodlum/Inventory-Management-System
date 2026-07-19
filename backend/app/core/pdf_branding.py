"""Shared PDF branding: draw the configured company logo into a document header.

The logo is an app-level setting (``COMPANY_LOGO_PATH``), consistent with the other
``company_*`` print settings. When unset or unreadable this is a no-op, so documents render
exactly as before — nothing is hard-coded and no branding ships in the repo.
"""
from __future__ import annotations

import functools
import io

from app.core.config import settings


def _latin1(text: str) -> str:
    return str(text).encode("latin-1", "replace").decode("latin-1")


def company_contact_lines(*, include_name: bool = False) -> tuple[str, ...]:
    """The company block every document prints: address, email, phone, and the tax
    identifier when configured.

    Defined once so a detail added here (like the tax id) appears on EVERY document rather
    than only the ones someone remembered to update. The tax label is configurable — TPIN,
    VAT No., TIN — so nothing country-specific is baked into the core. Blank entries are
    skipped by :func:`draw_company_block`.
    """
    tax = ""
    if settings.company_tax_id:
        label = (settings.company_tax_label or "Tax ID").strip()
        tax = f"{label}: {settings.company_tax_id}"
    lines = (settings.company_address, settings.company_email, settings.company_phone, tax)
    return ((settings.company_name,) + lines) if include_name else lines


def draw_company_block(pdf, x: float, y: float, width: float, lines) -> float:
    """Draw the company address block (name / address / email / phone) starting at (x, y),
    each line wrapped WITHIN ``width`` mm so it never bleeds into a right-hand meta column.
    Falsy lines are skipped. Returns the y coordinate just below the block."""
    cy = y
    for text in lines:
        if not text:
            continue
        pdf.set_xy(x, cy)
        pdf.multi_cell(width, 5, _latin1(text))
        cy = pdf.get_y()
    return cy


@functools.lru_cache(maxsize=4)
def _logo_bytes(path: str) -> bytes | None:
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def place_logo(pdf, x: float, y: float, max_w: float, max_h: float) -> float:
    """Draw the company logo at (x, y), scaled to fit ``max_w`` x ``max_h`` mm while
    preserving aspect ratio. Returns the drawn height in mm — ``0`` when no logo is
    configured (or it can't be read), so callers can lay out around it either way."""
    data = _logo_bytes(settings.company_logo_path)
    if not data:
        return 0.0
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            iw, ih = im.size
    except Exception:
        return 0.0
    if iw <= 0 or ih <= 0:
        return 0.0
    ratio = min(max_w / iw, max_h / ih)
    w, h = iw * ratio, ih * ratio
    try:
        pdf.image(io.BytesIO(data), x=x, y=y, w=w, h=h)
    except Exception:
        return 0.0
    return h
