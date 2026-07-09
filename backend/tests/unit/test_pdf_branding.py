"""The shared PDF logo helper: a no-op when unconfigured, draws (scaled to fit) when set."""
from __future__ import annotations

from fpdf import FPDF
from PIL import Image

from app.core import pdf_branding
from app.core.config import settings


def _pdf() -> FPDF:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    return pdf


def test_place_logo_is_a_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "company_logo_path", "")
    pdf_branding._logo_bytes.cache_clear()
    assert pdf_branding.place_logo(_pdf(), 15, 15, 45, 15) == 0.0


def test_place_logo_is_a_noop_when_file_missing(monkeypatch):
    monkeypatch.setattr(settings, "company_logo_path", "/no/such/logo.png")
    pdf_branding._logo_bytes.cache_clear()
    assert pdf_branding.place_logo(_pdf(), 15, 15, 45, 15) == 0.0


def test_place_logo_draws_scaled_to_fit(tmp_path, monkeypatch):
    p = tmp_path / "logo.png"
    Image.new("RGB", (300, 200), "white").save(p)   # 3:2 landscape
    monkeypatch.setattr(settings, "company_logo_path", str(p))
    pdf_branding._logo_bytes.cache_clear()

    pdf = _pdf()
    h = pdf_branding.place_logo(pdf, 15, 15, 45, 15)
    # Fits inside 45x15 mm preserving aspect: width binds at 45 -> height 30 > 15, so
    # height binds at 15 -> width 22.5. Height returned should be the 15mm cap.
    assert 0 < h <= 15
    assert bytes(pdf.output()).startswith(b"%PDF")
