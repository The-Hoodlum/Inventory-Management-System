"""Delivery / dispatch note PDF (fpdf2 — pure Python, no native deps).

Company header + from/to + mixed lines (motorcycles by chassis with engine, spare parts
by quantity) + received/missing columns + dispatch & receipt signature lines. Takes the
``DispatchNoteOut`` schema so it stays decoupled from the ORM.
"""
from __future__ import annotations

from typing import Any

from fpdf import FPDF

from app.core.config import settings
from app.core.pdf_branding import place_logo
from app.dispatch.schemas import DispatchNoteOut

_CONTENT_W = 180.0
_INK = (33, 37, 41)
_MUTED = (110, 116, 124)
_HEAD_BG = (242, 244, 247)
_LINE = (210, 214, 220)

_TYPE_LABELS = {
    "warehouse_branch_transfer": "Warehouse -> Branch Transfer",
    "branch_branch_transfer": "Branch -> Branch Transfer",
    "customer_delivery": "Customer Delivery",
    "internal_issuance": "Internal Issuance / Handover",
}


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _qty(v: Any) -> str:
    try:
        f = float(v)
    except Exception:
        return "0"
    return str(int(f)) if f == int(f) else f"{f:g}"


class _DNPdf(FPDF):
    company_name: str = ""

    def header(self) -> None:  # noqa: D401
        top = self.get_y()
        band = max(place_logo(self, 15, top, 45, 15), 10)
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_INK)
        self.cell(0, band, "DELIVERY NOTE", ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:  # noqa: D401
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{_s(self.company_name)}  -  Page {self.page_no()}/{{nb}}", align="C")


def build_dispatch_note_pdf(note: DispatchNoteOut) -> bytes:
    pdf = _DNPdf(orientation="P", unit="mm", format="A4")
    pdf.company_name = settings.company_name
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ---- Company (left) + note meta (right) ----
    top_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(95, 5, "From (company)", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    for part in (settings.company_name, settings.company_address, settings.company_email, settings.company_phone):
        if part:
            pdf.multi_cell(95, 5, _s(part))
    company_bottom = pdf.get_y()

    pdf.set_xy(115, top_y)
    for label, value in (
        ("Note No.", note.note_number),
        ("Type", _TYPE_LABELS.get(note.dispatch_type, note.dispatch_type)),
        ("Status", note.status.replace("_", " ").title()),
        ("Dispatched", note.dispatched_at.date().isoformat() if note.dispatched_at else "-"),
        ("Received", note.received_at.date().isoformat() if note.received_at else "-"),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(30, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(50, 5, _s(value), ln=1, align="R")
    pdf.set_y(max(company_bottom, pdf.get_y()) + 4)

    # ---- From / To locations ----
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(90, 5, "Dispatch from")
    pdf.cell(90, 5, "Deliver to", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    frm = "  |  ".join(b for b in (note.from_branch_name, note.from_warehouse_name) if b) or "-"
    to = "  |  ".join(b for b in (note.to_branch_name, note.to_warehouse_name) if b) or "-"
    pdf.cell(90, 5, _s(frm))
    pdf.cell(90, 5, _s(to), ln=1)
    pdf.ln(3)

    # ---- Lines ----
    cols = [("Item / Chassis", 78, "L"), ("Type", 24, "L"), ("Disp.", 22, "R"),
            ("Recv.", 22, "R"), ("Short", 22, "R")]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    for title, width, align in cols:
        pdf.cell(width, 7, _s(title), align=align, fill=True)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_draw_color(*_LINE)
    for ln_ in note.lines:
        if ln_.line_kind == "motorcycle":
            label = _s(ln_.chassis_number or "")
            sub = _s("  ".join(b for b in (ln_.model_name, f"Eng {ln_.engine_number}" if ln_.engine_number else None) if b))
            kind = "Motorcycle"
        else:
            label = _s(ln_.name or ln_.sku or "")
            sub = _s(ln_.sku or "")
            kind = "Spare part"
        if len(label) > 46:
            label = label[:45] + "..."
        short = float(ln_.missing_qty) + float(ln_.damaged_qty)
        for text_value, width, align in (
            (label, 78, "L"), (kind, 24, "L"), (_qty(ln_.dispatched_qty), 22, "R"),
            (_qty(ln_.received_qty), 22, "R"), (_qty(short) if short else "-", 22, "R"),
        ):
            pdf.cell(width, 6, text_value, border="B", align=align)
        pdf.ln(6)
        if sub:
            pdf.set_text_color(*_MUTED)
            pdf.set_font("Helvetica", "I", 7.5)
            pdf.cell(0, 4, f"   {sub}", ln=1)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_INK)

    # ---- Remarks ----
    if note.remarks:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5, "Remarks", ln=1)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 5, _s(note.remarks))

    # ---- Signatures ----
    pdf.ln(12)
    pdf.set_draw_color(*_LINE)
    sig_w = _CONTENT_W / 2
    y = pdf.get_y()
    for i, role in enumerate(("Dispatched by", "Received by")):
        x = 15 + i * sig_w
        pdf.line(x, y, x + sig_w - 10, y)
        pdf.set_xy(x, y + 1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(sig_w - 10, 4, _s(f"{role} (name / signature / date)"))

    return bytes(pdf.output())
