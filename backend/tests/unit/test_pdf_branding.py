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


def test_draw_company_block_stays_within_width_and_advances_y():
    pdf = _pdf()
    pdf.set_font("Helvetica", "", 9)
    y0 = pdf.get_y()
    end = pdf_branding.draw_company_block(
        pdf, 15, y0, 90,
        ("Example Trading Ltd", "1 Very Long Street Name, Some District, A City, A Country",
         "info@example.com", "+000 000000000", None, ""),
    )
    assert end > y0                      # advanced below the block
    assert pdf.get_x() <= 15 + 90 + 1    # never bled past the column width
    assert bytes(pdf.output()).startswith(b"%PDF")


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


# ------------------------- tax identifier on documents --------------------- #
def test_company_contact_lines_include_the_tax_id_when_configured(monkeypatch):
    """The label is configurable (TPIN / VAT No. / TIN) so the core stays country-agnostic."""
    from app.core import pdf_branding as pb
    from app.core.config import settings

    monkeypatch.setattr(settings, "company_address", "1 Main Rd", raising=False)
    monkeypatch.setattr(settings, "company_email", "info@example.com", raising=False)
    monkeypatch.setattr(settings, "company_phone", "+260 1", raising=False)
    monkeypatch.setattr(settings, "company_tax_label", "TPIN", raising=False)
    monkeypatch.setattr(settings, "company_tax_id", "2003807414", raising=False)

    assert "TPIN: 2003807414" in pb.company_contact_lines()


def test_tax_line_is_absent_until_an_id_is_set(monkeypatch):
    """A tenant that hasn't configured one prints no empty label."""
    from app.core import pdf_branding as pb
    from app.core.config import settings

    monkeypatch.setattr(settings, "company_tax_id", "", raising=False)
    assert all("TPIN" not in ln and "Tax ID" not in ln for ln in pb.company_contact_lines())


def test_company_name_is_included_only_when_asked(monkeypatch):
    from app.core import pdf_branding as pb
    from app.core.config import settings

    monkeypatch.setattr(settings, "company_name", "Example Trading Ltd", raising=False)
    assert pb.company_contact_lines(include_name=True)[0] == "Example Trading Ltd"
    assert "Example Trading Ltd" not in pb.company_contact_lines()
