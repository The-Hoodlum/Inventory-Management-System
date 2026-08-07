"""Customer Handover PDF (fpdf2 — pure Python, no native deps).

Renders the paper form's two copies:
  * CUSTOMER COPY  — customer + motorcycle details, items received, the customer
    declaration, both signatures, and the first-service reminder (500 KM / 30 days).
  * INTERNAL COPY  — everything: header, customer, motorcycle, the full pre-delivery
    checklist, training, accessories, payment, and the 5-role verification grid.

Company header/branding comes from ``core.pdf_branding`` (logo + address block), identical
to the other printed documents. ASCII-only (latin-1 core fonts): coerce every string with
``_s`` and never emit non-latin-1 glyphs.
"""
from __future__ import annotations

from typing import Any

from fpdf import FPDF

from app.core.config import settings
from app.core.pdf_branding import company_contact_lines, draw_company_block, place_logo
from app.customer_handovers.schemas import HandoverOut

_INK = (33, 37, 41)
_MUTED = (110, 116, 124)
_HEAD_BG = (242, 244, 247)
_LINE = (210, 214, 220)
_OK = (22, 130, 70)

# (field, label) in paper-form order.
_CHECKLIST = [
    ("motorcycle_washed", "Motorcycle washed"),
    ("battery_connected", "Battery connected"),
    ("engine_tested", "Engine tested"),
    ("brakes_tested", "Brakes tested"),
    ("lights_working", "Lights working"),
    ("indicators_working", "Indicators working"),
    ("horn_working", "Horn working"),
    ("mirrors_fitted", "Mirrors fitted"),
    ("tyre_pressure_checked", "Tyre pressure checked"),
    ("chain_adjusted", "Chain adjusted"),
    ("oil_level_checked", "Oil level checked"),
    ("throttle_operation_checked", "Throttle operation checked"),
    ("toolkit_supplied", "Toolkit supplied"),
    ("owners_manual_supplied", "Owner's manual supplied"),
    ("warranty_book_supplied", "Warranty book supplied"),
    ("spare_key_supplied", "Spare key supplied"),
]
_TRAINING = [
    ("controls_explained", "Controls explained"),
    ("break_in_period_explained", "Break-in period explained"),
    ("service_schedule_explained", "Service schedule explained"),
    ("warranty_terms_explained", "Warranty terms explained"),
    ("safe_riding_explained", "Safe riding explained"),
    ("maintenance_tips_explained", "Maintenance tips explained"),
]
_ACCESSORIES = [("helmet", "Helmet"), ("reflector_jacket", "Reflector jacket"), ("spare_key", "Spare key")]
_ROLE_LABELS = {
    "mechanic_inspector": "Mechanic / Inspector",
    "assembly_technician": "Assembly Technician",
    "quality_control_officer": "Quality Control Officer",
    "salesperson": "Salesperson",
    "branch_manager": "Branch Manager",
}
_FUEL_LABELS = {"E": "Empty", "1": "1/4", "2": "1/2", "3": "3/4", "F": "Full", "4": "3/4"}


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _money(v: Any) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return "0.00"


def _date(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return v.date().isoformat() if hasattr(v, "date") else v.isoformat()
    except Exception:
        return _s(v)


class _HandoverPdf(FPDF):
    company_name: str = ""
    doc_title: str = "CUSTOMER HANDOVER"

    def header(self) -> None:
        top = self.get_y()
        band = max(place_logo(self, 15, top, 45, 15), 10)
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(*_INK)
        self.cell(0, band, self.doc_title, ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(3)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{_s(self.company_name)}  -  Page {self.page_no()}/{{nb}}", align="C")


# --------------------------------------------------------------------------- #
# Small drawing helpers
# --------------------------------------------------------------------------- #
def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 7, f"  {_s(title)}", ln=1, fill=True)
    pdf.ln(1)


def _kv_row(pdf: FPDF, pairs: list[tuple[str, str]]) -> None:
    """Two label/value pairs per line (label muted, value ink)."""
    col = 90
    for i, (label, value) in enumerate(pairs):
        if i % 2 == 0:
            pdf.set_x(15)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(30, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(col - 30, 5, _s(value), ln=(1 if i % 2 == 1 else 0))
    if len(pairs) % 2 == 1:
        pdf.ln(5)


def _checkbox(pdf: FPDF, checked: bool, label: str, width: float) -> None:
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_draw_color(*_LINE)
    pdf.rect(x, y + 1, 3.5, 3.5)
    if checked:
        pdf.set_text_color(*_OK)
        pdf.set_font("Helvetica", "B", 9)
        pdf.text(x + 0.4, y + 4, "X")
    pdf.set_xy(x + 5, y)
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(width - 5, 5.5, _s(label))


def _checkbox_grid(pdf: FPDF, items: list[tuple[str, str]], obj: Any, cols: int = 2) -> None:
    col_w = 180.0 / cols
    for i, (field, label) in enumerate(items):
        if i % cols == 0:
            pdf.set_x(15)
        _checkbox(pdf, bool(getattr(obj, field, False)), label, col_w)
        if i % cols == cols - 1:
            pdf.ln(5.5)
    if len(items) % cols != 0:
        pdf.ln(5.5)


def _remarks(pdf: FPDF, label: str, text: str | None) -> None:
    if not text:
        return
    pdf.set_x(15)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(180, 4.5, _s(f"{label}: {text}"))


def _signature_lines(pdf: FPDF, roles: list[tuple[str, str]]) -> None:
    """Two signature blocks per row: (caption, printed name)."""
    pdf.ln(10)
    pdf.set_draw_color(*_LINE)
    half = 90.0
    for i, (caption, name) in enumerate(roles):
        x = 15 + (i % 2) * half
        if i % 2 == 0:
            pdf.set_x(15)
        y = pdf.get_y()
        pdf.line(x, y, x + half - 12, y)
        pdf.set_xy(x, y + 1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(half - 12, 4, _s(caption))
        if name:
            pdf.set_xy(x, y - 4)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*_INK)
            pdf.cell(half - 12, 4, _s(name))
        if i % 2 == 1:
            pdf.ln(12)
    if len(roles) % 2 == 1:
        pdf.ln(12)


def _meta_block(pdf: FPDF, h: HandoverOut) -> None:
    """Handover number / status / dates in the top-right, next to the company block."""
    top_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(95, 5, _s(settings.company_name or "Company"), ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    company_bottom = draw_company_block(pdf, 15, pdf.get_y(), 90, company_contact_lines())

    pdf.set_xy(115, top_y)
    for label, value in (
        ("Handover No.", h.handover_no),
        ("Status", h.status.title()),
        ("Delivery date", _date(h.delivery_date)),
        ("Invoice", h.invoice_number or "-"),
        ("Branch", h.branch_name or "-"),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(30, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(50, 5, _s(value), ln=1, align="R")
    pdf.set_y(max(company_bottom, pdf.get_y()) + 3)


def _customer_and_bike(pdf: FPDF, h: HandoverOut) -> None:
    _section(pdf, "Customer")
    _kv_row(pdf, [("Name", h.full_name or "-"), ("NRC / Passport", h.nrc_passport_no or "-")])
    _kv_row(pdf, [("Phone", h.phone or "-"), ("WhatsApp", h.whatsapp or "-")])
    _kv_row(pdf, [("Email", h.email or "-"), ("Salesperson", h.salesperson_display or "-")])
    _kv_row(pdf, [("Address", h.physical_address or "-"), ("", "")])

    _section(pdf, "Motorcycle")
    _kv_row(pdf, [("Model", h.model_name or "-"), ("Colour", h.colour_name or "-")])
    _kv_row(pdf, [("Chassis / VIN", h.chassis_number or "-"), ("Engine No.", h.engine_number or "-")])
    fuel = _FUEL_LABELS.get(str(h.fuel_level_at_delivery), "-") if h.fuel_level_at_delivery else "-"
    odo = f"{_money(h.odometer_reading_km)} km" if h.odometer_reading_km is not None else "-"
    _kv_row(pdf, [("Odometer", odo), ("Fuel at delivery", fuel)])
    _kv_row(pdf, [("Warranty start", _date(h.warranty_start_date)), ("", "")])


def _first_service_note(pdf: FPDF) -> None:
    pdf.ln(2)
    pdf.set_fill_color(255, 249, 224)
    pdf.set_draw_color(230, 210, 140)
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "  First service reminder", ln=1, fill=True, border=1)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_x(15)
    pdf.multi_cell(
        180, 4.6,
        _s("Please return for your FIRST FREE SERVICE at 500 KM or within 30 days of "
           "delivery, whichever comes first. Failure to do so may affect your warranty."),
    )


# --------------------------------------------------------------------------- #
# Copies
# --------------------------------------------------------------------------- #
def _customer_copy(pdf: _HandoverPdf, h: HandoverOut) -> None:
    pdf.doc_title = "CUSTOMER HANDOVER - CUSTOMER COPY"
    pdf.add_page()
    _meta_block(pdf, h)
    _customer_and_bike(pdf, h)

    _section(pdf, "Items received")
    _checkbox_grid(pdf, _ACCESSORIES, h, cols=3)
    if h.other_items:
        _remarks(pdf, "Other items", h.other_items)

    _first_service_note(pdf)

    _section(pdf, "Customer declaration")
    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(
        180, 4.6,
        _s("I confirm that I have received the motorcycle described above in good condition, "
           "that its controls, service schedule and warranty terms have been explained to me, "
           "and that I accept the items and documents listed."),
    )
    _signature_lines(
        pdf,
        [
            (f"Customer signature / date{_dt(h.customer_signed_at)}", h.customer_signature_name or ""),
            (f"For {settings.company_name or 'the company'} / date", h.salesperson_signature_name or h.salesperson_display or ""),
        ],
    )


def _internal_copy(pdf: _HandoverPdf, h: HandoverOut) -> None:
    pdf.doc_title = "CUSTOMER HANDOVER - INTERNAL COPY"
    pdf.add_page()
    _meta_block(pdf, h)
    _customer_and_bike(pdf, h)

    _section(pdf, "Pre-delivery checklist")
    _checkbox_grid(pdf, _CHECKLIST, h, cols=2)
    _remarks(pdf, "Checklist remarks", h.checklist_remarks)

    _section(pdf, "Customer training")
    _checkbox_grid(pdf, _TRAINING, h, cols=2)
    _remarks(pdf, "Training remarks", h.training_remarks)

    _section(pdf, "Items / accessories")
    _checkbox_grid(pdf, _ACCESSORIES, h, cols=3)
    _remarks(pdf, "Other items", h.other_items)

    _section(pdf, "Payment")
    _kv_row(pdf, [("Method", h.payment_method or "-"), ("Invoice amount (ZMW)", _money(h.invoice_amount_zmw))])
    _kv_row(pdf, [("Amount paid (ZMW)", _money(h.amount_paid_zmw)), ("Balance (ZMW)", _money(h.balance_zmw))])
    _remarks(pdf, "Internal remarks", h.internal_remarks)

    _section(pdf, "Verification & approval")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    for title, w in (("Role", 55), ("Name", 70), ("Signed", 25), ("Date", 30)):
        pdf.cell(w, 6, f" {_s(title)}", fill=True, border="B")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8.5)
    for ap in h.approvals:
        pdf.set_x(15)
        pdf.set_text_color(*_INK)
        pdf.cell(55, 6, f" {_s(_ROLE_LABELS.get(ap.role, ap.role))}", border="B")
        pdf.cell(70, 6, _s(ap.name or "-"), border="B")
        if ap.signed:
            pdf.set_text_color(*_OK)
            pdf.cell(25, 6, "Yes", border="B")
        else:
            pdf.set_text_color(*_MUTED)
            pdf.cell(25, 6, "No", border="B")
        pdf.set_text_color(*_INK)
        pdf.cell(30, 6, _s(_date(ap.signed_at)), border="B")
        pdf.ln(6)

    _signature_lines(
        pdf,
        [
            (f"Customer signature / date{_dt(h.customer_signed_at)}", h.customer_signature_name or ""),
            ("Salesperson signature / date", h.salesperson_signature_name or h.salesperson_display or ""),
        ],
    )


def _dt(v: Any) -> str:
    return f"  ({_date(v)})" if v else ""


def build_handover_pdf(h: HandoverOut, *, copy: str = "both") -> bytes:
    pdf = _HandoverPdf(orientation="P", unit="mm", format="A4")
    pdf.company_name = settings.company_name or ""
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()

    if copy in ("customer", "both"):
        _customer_copy(pdf, h)
    if copy in ("internal", "both"):
        _internal_copy(pdf, h)

    return bytes(pdf.output())
