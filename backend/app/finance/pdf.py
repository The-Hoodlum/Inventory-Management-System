"""Cash handover slip (fpdf2). A printable record of a branch cash handover: both names
(handed over by / received by), the amount, the optional denomination breakdown, any
discrepancy, and signature lines — mirroring the other document PDFs' branding + layout."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fpdf import FPDF

from app.core.config import settings
from app.core.pdf_branding import draw_company_block, place_logo
from app.finance.schemas import HandoverOut

_CONTENT_W = 180.0
_INK = (33, 37, 41)
_MUTED = (110, 116, 124)
_HEAD_BG = (242, 244, 247)
_LINE = (210, 214, 220)


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _money(v: Any) -> str:
    try:
        return f"{Decimal(str(v)):,.2f}"
    except Exception:
        return "-"


class _SlipPdf(FPDF):
    company_name: str = ""

    def header(self) -> None:  # noqa: D401
        top = self.get_y()
        band = max(place_logo(self, 15, top, 45, 15), 10)
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_INK)
        self.cell(0, band, "CASH HANDOVER SLIP", ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:  # noqa: D401
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{_s(self.company_name)}  -  Page {self.page_no()}/{{nb}}", align="C")


def build_handover_slip_pdf(h: HandoverOut) -> bytes:
    pdf = _SlipPdf(orientation="P", unit="mm", format="A4")
    pdf.company_name = settings.company_name
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ---- Header meta ----
    top_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(95, 5, _s(settings.company_name or "Company"), ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    left_bottom = draw_company_block(
        pdf, 15, pdf.get_y(), 90,
        (settings.company_address, settings.company_email, settings.company_phone),
    )
    pdf.set_xy(115, top_y)
    for label, value in (
        ("Reference", h.reference_no or f"HO-{str(h.id)[:8]}"),
        ("Branch", h.branch_name or "-"),
        ("Date / time", h.handover_datetime.strftime("%Y-%m-%d %H:%M") if h.handover_datetime else "-"),
        ("Status", h.status.replace("_", " ").title()),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(32, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(48, 5, _s(value), ln=1, align="R")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 3)

    # ---- Parties + accounts ----
    pdf.set_font("Helvetica", "", 9)
    for label, value in (
        ("Handed over by", h.handed_over_by_name or "-"),
        ("Received by", h.received_by_name),
        ("From account", h.from_account_name or "-"),
        ("To account", h.to_account_name or "-"),
    ):
        pdf.set_x(15)
        pdf.set_text_color(*_MUTED)
        pdf.cell(38, 6, _s(label))
        pdf.set_text_color(*_INK)
        pdf.set_font("Helvetica", "B" if label in ("Handed over by", "Received by") else "", 9)
        pdf.cell(0, 6, _s(value), ln=1)
        pdf.set_font("Helvetica", "", 9)
    pdf.ln(2)

    # ---- Amount ----
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(90, 10, "  Amount handed over", border=0, fill=True)
    pdf.cell(90, 10, f"ZMW {_money(h.amount)}  ", border=0, fill=True, align="R", ln=1)
    if h.confirmed_amount is not None:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(90, 6, "  Amount confirmed / counted")
        pdf.cell(90, 6, f"ZMW {_money(h.confirmed_amount)}  ", align="R", ln=1)
        if h.discrepancy_amount is not None and Decimal(str(h.discrepancy_amount)) != 0:
            pdf.set_text_color(180, 40, 40)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(90, 6, "  Discrepancy")
            pdf.cell(90, 6, f"ZMW {_money(h.discrepancy_amount)}  ", align="R", ln=1)
            pdf.set_font("Helvetica", "", 8)
            pdf.multi_cell(0, 4.5, _s(f"  Reason: {h.discrepancy_reason or '-'}"))
            pdf.set_text_color(*_INK)
    pdf.ln(2)

    # ---- Denomination breakdown ----
    denom = h.denomination_breakdown or {}
    if isinstance(denom, dict) and denom:
        pdf.set_text_color(*_INK)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, "Denomination breakdown", ln=1)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_fill_color(*_HEAD_BG)
        pdf.cell(60, 6, "Denomination", border="B", fill=True)
        pdf.cell(40, 6, "Count", border="B", fill=True, align="R", ln=1)
        for k, v in denom.items():
            pdf.cell(60, 6, _s(k), border="B")
            pdf.cell(40, 6, _s(v), border="B", align="R", ln=1)
        pdf.ln(2)

    if h.notes:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 4.5, _s(f"Notes: {h.notes}"))

    # ---- Signatures (both named parties) ----
    pdf.ln(12)
    pdf.set_draw_color(*_LINE)
    sig_w = _CONTENT_W / 2
    y = pdf.get_y()
    for i, (role, name) in enumerate((("Handed over by", h.handed_over_by_name),
                                      ("Received by", h.received_by_name))):
        x = 15 + i * sig_w
        pdf.line(x, y, x + sig_w - 10, y)
        pdf.set_xy(x, y + 1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(sig_w - 10, 4, _s(f"{role}: {name or '________'}  (signature / date)"))

    return bytes(pdf.output())
