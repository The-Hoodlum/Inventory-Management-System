"""Internal issuance / handover PDF (fpdf2). Follows a handover-form layout: requestor /
department / purpose + expected return, bike lines (chassis, odometer, fuel, accessories),
item lines, handover terms, and dispatch + return signature lines."""
from __future__ import annotations

from typing import Any

from fpdf import FPDF

from app.core.config import settings
from app.issuance.schemas import IssuanceOut

_CONTENT_W = 180.0
_INK = (33, 37, 41)
_MUTED = (110, 116, 124)
_HEAD_BG = (242, 244, 247)
_LINE = (210, 214, 220)

_TERMS = (
    "The items above are issued ON LOAN and remain company property. The recipient is "
    "responsible for their safekeeping and must return them by the expected date in the "
    "condition issued. Any loss or damage must be reported on return."
)


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _num(v: Any) -> str:
    try:
        f = float(v)
    except Exception:
        return "-"
    return str(int(f)) if f == int(f) else f"{f:g}"


class _IssPdf(FPDF):
    company_name: str = ""

    def header(self) -> None:  # noqa: D401
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_INK)
        self.cell(0, 10, "HANDOVER / ISSUANCE NOTE", ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:  # noqa: D401
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{_s(self.company_name)}  -  Page {self.page_no()}/{{nb}}", align="C")


def build_issuance_pdf(iss: IssuanceOut) -> bytes:
    pdf = _IssPdf(orientation="P", unit="mm", format="A4")
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
    for part in (settings.company_address, settings.company_phone):
        if part:
            pdf.multi_cell(95, 5, _s(part))
    left_bottom = pdf.get_y()

    pdf.set_xy(115, top_y)
    for label, value in (
        ("Issuance No.", iss.issuance_number),
        ("Status", iss.status.replace("_", " ").title()),
        ("Issued", iss.issued_at.date().isoformat() if iss.issued_at else "-"),
        ("Expected back", iss.expected_return_date.isoformat() if iss.expected_return_date else "-"),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(32, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(48, 5, _s(value), ln=1, align="R")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 3)

    # ---- Requestor / department / purpose ----
    pdf.set_font("Helvetica", "", 9)
    for label, value in (("Requestor", iss.requestor), ("Department", iss.department), ("Purpose / activity", iss.purpose)):
        pdf.set_x(15)
        pdf.set_text_color(*_MUTED)
        pdf.cell(35, 5, _s(label))
        pdf.set_text_color(*_INK)
        text = _s(value or "-")
        pdf.cell(0, 5, text[:110], ln=1)
    pdf.ln(2)

    # ---- Lines ----
    cols = [("Item / Chassis", 74, "L"), ("Kind", 20, "L"), ("Qty", 14, "R"),
            ("Returnable", 24, "C"), ("Details", 48, "L")]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    for title, width, align in cols:
        pdf.cell(width, 7, _s(title), align=align, fill=True)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_draw_color(*_LINE)
    for ln_ in iss.lines:
        if ln_.line_kind == "motorcycle":
            label = _s(ln_.chassis_number or "")
            detail_bits = [ln_.model_name, f"Odo {_num(ln_.odometer_out)}" if ln_.odometer_out is not None else None,
                           f"Fuel {ln_.fuel_out}" if ln_.fuel_out else None, ln_.accessories]
            kind = "Bike"
        else:
            label = _s(ln_.name or ln_.sku or "")
            detail_bits = [ln_.sku, "consumable" if ln_.consumable else None]
            kind = "Item"
        detail = _s("  ".join(b for b in detail_bits if b))
        if len(label) > 44:
            label = label[:43] + "..."
        if len(detail) > 30:
            detail = detail[:29] + "..."
        ret = "No" if not ln_.returnable else "Yes"
        for text_value, width, align in (
            (label, 74, "L"), (kind, 20, "L"), (_num(ln_.qty), 14, "R"), (ret, 24, "C"), (detail, 48, "L"),
        ):
            pdf.cell(width, 6, text_value, border="B", align=align)
        pdf.ln(6)

    # ---- Terms ----
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 5, "Handover terms", ln=1)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 4.5, _s(_TERMS))
    if iss.remarks:
        pdf.ln(1)
        pdf.multi_cell(0, 4.5, _s(f"Remarks: {iss.remarks}"))

    # ---- Signatures ----
    pdf.ln(10)
    pdf.set_draw_color(*_LINE)
    sig_w = _CONTENT_W / 2
    y = pdf.get_y()
    for i, role in enumerate(("Issued by", "Received by (recipient)")):
        x = 15 + i * sig_w
        pdf.line(x, y, x + sig_w - 10, y)
        pdf.set_xy(x, y + 1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(sig_w - 10, 4, _s(f"{role} (name / signature / date)"))

    return bytes(pdf.output())
