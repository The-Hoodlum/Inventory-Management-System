"""Purchase-order PDF rendering (fpdf2 — pure Python, no native dependencies).

``build_purchase_order_pdf`` takes plain dictionaries (assembled by the service)
so it stays decoupled from the ORM and is easy to test. Returns PDF bytes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fpdf import FPDF

from app.core.pdf_branding import draw_company_block, place_logo

# A4 content width: 210mm - 2 x 15mm margins.
_CONTENT_W = 180.0
_INK = (33, 37, 41)
_MUTED = (110, 116, 124)
_HEAD_BG = (242, 244, 247)
_LINE = (210, 214, 220)


def _s(value: Any) -> str:
    """Coerce to a latin-1-safe string (fpdf2 core fonts are latin-1)."""
    if value is None:
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _money(value: Any, currency: str = "") -> str:
    try:
        amount = Decimal(str(value))
    except Exception:
        amount = Decimal("0")
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{amount:,.2f}"


class _POPdf(FPDF):
    company_name: str = ""

    def header(self) -> None:  # noqa: D401 - fpdf hook
        top = self.get_y()
        band = max(place_logo(self, 15, top, 45, 15), 10)
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_INK)
        self.cell(0, band, "PURCHASE ORDER", ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:  # noqa: D401 - fpdf hook
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{_s(self.company_name)}  -  Page {self.page_no()}/{{nb}}", align="C")


def build_purchase_order_pdf(
    *,
    company: dict[str, Any],
    supplier: dict[str, Any],
    po: dict[str, Any],
    lines: list[dict[str, Any]],
    terms: str = "",
) -> bytes:
    currency = _s(po.get("currency", ""))

    pdf = _POPdf(orientation="P", unit="mm", format="A4")
    pdf.company_name = company.get("name", "")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ---- From (company) and PO meta, side by side ----
    top_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(95, 5, "From", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    company_bottom = draw_company_block(
        pdf, 15, pdf.get_y(), 90,
        (company.get("name"), company.get("address"), company.get("email"),
         company.get("phone"), company.get("tax")),
    )

    # PO meta block on the right
    pdf.set_xy(115, top_y)
    pdf.set_font("Helvetica", "", 9)
    meta = [
        ("PO Number", po.get("po_number")),
        ("Status", str(po.get("status", "")).replace("_", " ").title()),
        ("Order Date", po.get("order_date")),
        ("Expected", po.get("expected_date") or "-"),
        ("Currency", currency),
    ]
    for label, value in meta:
        pdf.set_x(115)
        pdf.set_text_color(*_MUTED)
        pdf.cell(30, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(50, 5, _s(value), ln=1, align="R")

    pdf.set_y(max(company_bottom, pdf.get_y()) + 4)

    # ---- Supplier ----
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 5, "Supplier", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    sup_bits = [
        supplier.get("name"),
        supplier.get("contact_person"),
        supplier.get("email"),
        supplier.get("phone"),
        supplier.get("country"),
    ]
    pdf.multi_cell(0, 5, _s("  |  ".join(b for b in sup_bits if b)))
    pdf.ln(3)

    # ---- Line items table ----
    cols = [
        ("Item", 70, "L"),
        ("Qty", 20, "R"),
        ("UPC", 15, "R"),
        ("Cartons", 20, "R"),
        ("Unit Cost", 27, "R"),
        ("Line Total", 28, "R"),
    ]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    for title, width, align in cols:
        pdf.cell(width, 7, _s(title), border=0, align=align, fill=True)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_draw_color(*_LINE)
    for item in lines:
        name = _s(item.get("name") or item.get("sku") or "")
        sku = _s(item.get("sku") or "")
        label = f"{name}" + (f"  ({sku})" if sku and sku != name else "")
        if len(label) > 48:
            label = label[:47] + "…"
        row = [
            (label, 70, "L"),
            (_s(item.get("ordered_qty")), 20, "R"),
            (_s(item.get("units_per_carton") or "-"), 15, "R"),
            (_s(item.get("cartons") if item.get("cartons") is not None else "-"), 20, "R"),
            (_money(item.get("unit_cost"), currency), 27, "R"),
            (_money(item.get("line_total"), currency), 28, "R"),
        ]
        for text_value, width, align in row:
            pdf.cell(width, 6, text_value, border="B", align=align)
        pdf.ln(6)

    # ---- Totals ----
    pdf.ln(2)
    label_w, val_w = _CONTENT_W - 50, 50
    for label, value, bold in (
        ("Subtotal", po.get("subtotal"), False),
        ("Tax", po.get("tax"), False),
        ("Total", po.get("total"), True),
    ):
        pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
        pdf.set_text_color(*_INK if bold else _MUTED)
        pdf.cell(label_w, 6, _s(label), align="R")
        pdf.set_text_color(*_INK)
        pdf.cell(val_w, 6, _money(value, currency), align="R", ln=1)

    # ---- Notes & terms ----
    if po.get("notes"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5, "Notes", ln=1)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 5, _s(po["notes"]))

    if terms:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5, "Terms & Conditions", ln=1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 4.5, _s(terms))

    # ---- Signature areas ----
    pdf.ln(10)
    pdf.set_draw_color(*_LINE)
    sig_w = _CONTENT_W / 3
    y = pdf.get_y()
    for i, role in enumerate(("Prepared by", "Approved by", "Received by")):
        x = 15 + i * sig_w
        pdf.line(x, y, x + sig_w - 8, y)
        pdf.set_xy(x, y + 1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(sig_w - 8, 4, _s(f"{role} (name / signature / date)"))

    return bytes(pdf.output())
