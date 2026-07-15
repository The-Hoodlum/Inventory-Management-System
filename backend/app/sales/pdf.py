"""Sales invoice PDF (fpdf2). Branded letterhead (logo + company block), Bill-To, line
items, and totals in the billed currency. For a motorcycle sale the invoice has no fungible
lines, so the linked bike is shown as a single line."""
from __future__ import annotations

from typing import Any

from fpdf import FPDF

from app.core.config import settings
from app.core.pdf_branding import draw_company_block, place_logo
from app.sales.schemas import InvoiceOut, QuotationOut

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
        return f"{float(v):,.2f}"
    except Exception:
        return "0.00"


def _bill_to(pdf: FPDF, doc: Any) -> None:
    """Draw the customer block (name / phone / address / tax number) shown on documents."""
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 5, "Bill to", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 5, _s(getattr(doc, "customer_name", None) or "-"), ln=1)
    for label, value in (
        ("", getattr(doc, "customer_address", None)),
        ("Tel: ", getattr(doc, "customer_phone", None)),
        ("Tax No: ", getattr(doc, "customer_tax_number", None)),
    ):
        if value:
            pdf.cell(0, 5, _s(f"{label}{value}"), ln=1)


class _InvPdf(FPDF):
    company_name: str = ""

    def header(self) -> None:  # noqa: D401
        top = self.get_y()
        band = max(place_logo(self, 15, top, 45, 15), 10)
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_INK)
        self.cell(0, band, "INVOICE", ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:  # noqa: D401
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{_s(self.company_name)}  -  Page {self.page_no()}/{{nb}}", align="C")


def build_invoice_pdf(
    inv: InvoiceOut, *, bikes: list | None = None, bike: tuple | None = None,
    currency: str = "", payments: list | None = None,
) -> bytes:
    # ``bikes`` = every serialized bike on the invoice (one for a single sale, several for a
    # bulk sale). ``bike`` is the legacy single-tuple form, still accepted.
    if bikes is None:
        bikes = [bike] if bike is not None else []
    cur = currency or inv.currency or ""
    pdf = _InvPdf(orientation="P", unit="mm", format="A4")
    pdf.company_name = settings.company_name
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ---- Company (left) + invoice meta (right) ----
    top_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(95, 5, "From", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    left_bottom = draw_company_block(
        pdf, 15, pdf.get_y(), 90,
        (settings.company_name, settings.company_address, settings.company_email, settings.company_phone),
    )

    pdf.set_xy(115, top_y)
    for label, value in (
        ("Invoice No.", inv.invoice_number),
        ("Date", inv.invoice_date.isoformat() if inv.invoice_date else "-"),
        ("Due", inv.due_date.isoformat() if inv.due_date else "-"),
        ("Status", inv.status.replace("_", " ").title()),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(32, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(48, 5, _s(value), ln=1, align="R")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 3)

    # ---- Bill to (full customer details) ----
    _bill_to(pdf, inv)
    pdf.ln(2)

    # ---- Lines (amounts in the billed currency) ----
    cols = [("Description", 96, "L"), ("Qty", 16, "R"), (f"Unit ({cur})", 34, "R"), (f"Total ({cur})", 34, "R")]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    for title, width, align in cols:
        pdf.cell(width, 7, _s(title), align=align, fill=True)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_draw_color(*_LINE)
    rows: list[tuple[str, float, float, float]] = []
    pending_chassis: list[str] = []
    for b in bikes:
        # 4-tuple (chassis, model, price, assembly_pending); tolerate older 3-tuples.
        chassis, model_name, price, *rest = b
        if rest and bool(rest[0]):
            pending_chassis.append(str(chassis))
        rows.append((f"Motorcycle - {model_name or 'unit'} (chassis {chassis})", 1.0, float(price), float(price)))
    for ln_ in inv.lines:
        desc = ln_.description or ln_.name or ln_.sku or ""
        total_zmw = ln_.line_total_zmw or 0.0
        unit_zmw = (total_zmw / ln_.qty) if ln_.qty else 0.0
        rows.append((desc, ln_.qty, unit_zmw, total_zmw))

    for desc, qty, unit_price, line_total in rows:
        d = _s(desc)
        if len(d) > 62:
            d = d[:61] + "..."
        for text_value, width, align in (
            (d, 96, "L"), (_money(qty) if qty != int(qty) else str(int(qty)), 16, "R"),
            (_money(unit_price), 34, "R"), (_money(line_total), 34, "R"),
        ):
            pdf.cell(width, 6, text_value, border="B", align=align)
        pdf.ln(6)

    # ---- Bikes sold before assembly: flag that they are not yet assembled ----
    if pending_chassis:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(0xB4, 0x53, 0x09)   # amber
        which = "" if len(pending_chassis) == len(rows) else " (" + ", ".join(pending_chassis) + ")"
        pdf.cell(0, 5, _s(f"Assembly status: NOT YET ASSEMBLED{which} - to be assembled before delivery."), ln=1)
        pdf.set_text_color(*_INK)

    # ---- Totals (billed ZMW payable) with the VAT broken out. net/vat are stored in the
    # document's line currency; convert to the billed currency at the frozen fx_rate. ----
    fx = inv.fx_rate or 1.0
    net_zmw = (inv.net_total or 0.0) * fx
    vat_zmw = (inv.tax_total or 0.0) * fx
    vat_label = f"VAT ({_money(inv.vat_rate * 100)}%)" if inv.vat_rate else "VAT"
    pdf.ln(2)
    for label, value, bold in (
        ("Net", net_zmw, False),
        (vat_label, vat_zmw, False),
        ("Total", inv.grand_total_zmw, True),
        ("Paid", inv.amount_paid, False),
        ("Balance", inv.balance, True),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "B" if bold else "", 9.5 if bold else 9)
        pdf.set_text_color(*_INK if bold else _MUTED)
        pdf.cell(40, 6, _s(label))
        pdf.cell(40, 6, f"{cur} {_money(value)}", ln=1, align="R")

    # ---- How it was paid: per-method breakdown + balance due ----
    if payments:
        pdf.ln(3)
        pdf.set_x(15)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5, "Payments received", ln=1)
        pdf.set_font("Helvetica", "", 8.5)
        for p in payments:
            method = _s(str(getattr(p, "method", "")).replace("_", " ").title())
            ref = getattr(p, "reference", None)
            when = getattr(p, "created_at", None)
            bits = [when.date().isoformat()] if when else []
            if ref:
                bits.append(f"ref {ref}")
            suffix = f"  ({', '.join(bits)})" if bits else ""
            pdf.set_x(15)
            pdf.set_text_color(*_MUTED)
            pdf.cell(120, 5, _s(f"{method}{suffix}"))
            pdf.set_text_color(*_INK)
            pdf.cell(60, 5, f"{cur} {_money(getattr(p, 'amount', 0))}", ln=1, align="R")
        pdf.set_x(15)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(120, 5, "Balance due")
        pdf.cell(60, 5, f"{cur} {_money(inv.balance)}", ln=1, align="R")

    # ---- VAT treatment note ----
    pdf.ln(3)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*_MUTED)
    note = ("Motorcycle prices are VAT-inclusive (VAT shown is extracted from the price); "
            "spare-part VAT is added to the net price.")
    pdf.multi_cell(180, 4, _s(note))

    return bytes(pdf.output())


class _QuotePdf(_InvPdf):
    def header(self) -> None:  # noqa: D401
        top = self.get_y()
        band = max(place_logo(self, 15, top, 45, 15), 10)
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_INK)
        self.cell(0, band, "QUOTATION", ln=1, align="R")
        self.set_draw_color(*_LINE)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.ln(4)


def build_quotation_pdf(q: QuotationOut, *, currency: str = "") -> bytes:
    """Branded quotation PDF — same letterhead + Bill-To as the invoice, line items and
    Net / VAT / Total in the billed currency. Amounts convert to the billed currency at the
    quotation's frozen fx_rate (bikes/direct-currency lines already sit at fx 1)."""
    cur = currency or q.currency or ""
    fx = q.fx_rate or 1.0
    pdf = _QuotePdf(orientation="P", unit="mm", format="A4")
    pdf.company_name = settings.company_name
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()
    pdf.add_page()

    top_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(95, 5, "From", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    left_bottom = draw_company_block(
        pdf, 15, pdf.get_y(), 90,
        (settings.company_name, settings.company_address, settings.company_email, settings.company_phone),
    )
    pdf.set_xy(115, top_y)
    for label, value in (
        ("Quote No.", q.quote_number),
        ("Date", q.created_at.date().isoformat() if q.created_at else "-"),
        ("Valid until", q.valid_until.isoformat() if q.valid_until else "-"),
        ("Status", q.status.replace("_", " ").title()),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(32, 5, _s(label))
        pdf.set_text_color(*_INK)
        pdf.cell(48, 5, _s(value), ln=1, align="R")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 3)

    _bill_to(pdf, q)
    pdf.ln(2)

    cols = [("Description", 96, "L"), ("Qty", 16, "R"), (f"Unit ({cur})", 34, "R"), (f"Total ({cur})", 34, "R")]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_HEAD_BG)
    pdf.set_text_color(*_INK)
    for title, width, align in cols:
        pdf.cell(width, 7, _s(title), align=align, fill=True)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_draw_color(*_LINE)
    for ln_ in q.lines:
        desc = ln_.description or ln_.name or ln_.sku or ""
        total_zmw = ln_.line_total_zmw or (ln_.line_total * fx)
        unit_zmw = (total_zmw / ln_.qty) if ln_.qty else 0.0
        d = _s(desc)
        if len(d) > 62:
            d = d[:61] + "..."
        for text_value, width, align in (
            (d, 96, "L"),
            (_money(ln_.qty) if ln_.qty != int(ln_.qty) else str(int(ln_.qty)), 16, "R"),
            (_money(unit_zmw), 34, "R"), (_money(total_zmw), 34, "R"),
        ):
            pdf.cell(width, 6, text_value, border="B", align=align)
        pdf.ln(6)

    # A quotation is denominated in ZMW: net_total / tax_total / grand_total are already
    # the billed ZMW (part lines converted at fx, bike lines direct) — do NOT re-convert.
    vat_label = f"VAT ({_money(q.vat_rate * 100)}%)" if q.vat_rate else "VAT"
    pdf.ln(2)
    for label, value, bold in (
        ("Net", q.net_total or 0.0, False),
        (vat_label, q.tax_total or 0.0, False),
        ("Total", q.grand_total_zmw or q.grand_total, True),
    ):
        pdf.set_x(115)
        pdf.set_font("Helvetica", "B" if bold else "", 9.5 if bold else 9)
        pdf.set_text_color(*_INK if bold else _MUTED)
        pdf.cell(40, 6, _s(label))
        pdf.cell(40, 6, f"{cur} {_money(value)}", ln=1, align="R")

    pdf.ln(3)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(180, 4, _s(
        "This is a quotation, not a tax invoice. Motorcycle prices are VAT-inclusive; "
        "spare-part VAT is added to the net price. Prices valid until the date shown."
    ))
    return bytes(pdf.output())
