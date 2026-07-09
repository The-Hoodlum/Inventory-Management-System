"""Shared PDF branding: draw the configured company logo into a document header.

The logo is an app-level setting (``COMPANY_LOGO_PATH``), consistent with the other
``company_*`` print settings. When unset or unreadable this is a no-op, so documents render
exactly as before — nothing is hard-coded and no branding ships in the repo.
"""
from __future__ import annotations

import functools
import io

from app.core.config import settings


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
