"""The invoice PDF renders a per-method payment breakdown + balance due when payments are
passed (item 5). Pure render — no DB; uses SimpleNamespace stand-ins for the invoice + its
payment lines (the builder only reads attributes)."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.sales.pdf import build_invoice_pdf


def _invoice(**over):
    base = dict(
        invoice_number="INV-2026-00042", invoice_date=dt.date(2026, 7, 1), due_date=None,
        status="partially_paid", currency="ZMW", customer_name="Aaron Sakala",
        customer_address="Lusaka", customer_phone=None, customer_tax_number=None,
        lines=[], fx_rate=1.0, net_total=172413.79, tax_total=27586.21,
        grand_total_zmw=200000.0, amount_paid=170000.0, balance=30000.0, vat_rate=0.16,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_invoice_pdf_renders_with_split_payment_breakdown():
    payments = [
        SimpleNamespace(method="cash", amount=120000.0, reference="C-1", created_at=dt.datetime(2026, 7, 1)),
        SimpleNamespace(method="bank_transfer", amount=50000.0, reference="TXN-9", created_at=dt.datetime(2026, 7, 1)),
    ]
    out = build_invoice_pdf(_invoice(), currency="ZMW", payments=payments)
    assert isinstance(out, bytes) and out[:4] == b"%PDF" and len(out) > 800


def test_invoice_pdf_renders_without_payments():
    # A brand-new unpaid invoice (no payments) still renders fine.
    out = build_invoice_pdf(_invoice(amount_paid=0.0, balance=200000.0, status="sent"), currency="ZMW")
    assert isinstance(out, bytes) and out[:4] == b"%PDF"


def test_invoice_pdf_bike_sold_before_assembly_renders():
    # A bike sold before assembly (4-tuple, assembly_pending=True) flags "NOT YET ASSEMBLED".
    bike = ("CH-123", "HLX 125", 20000.0, True)
    out = build_invoice_pdf(_invoice(), bike=bike, currency="ZMW")
    assert isinstance(out, bytes) and out[:4] == b"%PDF"


def test_invoice_pdf_tolerates_legacy_3tuple_bike():
    # An older 3-tuple bike (no assembly flag) must still render.
    out = build_invoice_pdf(_invoice(), bike=("CH-9", "RTR 200", 56000.0), currency="ZMW")
    assert isinstance(out, bytes) and out[:4] == b"%PDF"


def test_invoice_pdf_bulk_multiple_bikes_renders():
    # A bulk sale: several bikes on one invoice, one of them not yet assembled.
    bikes = [
        ("CH-1", "HLX 125", 20000.0, False),
        ("CH-2", "RTR 200", 56000.0, True),
        ("CH-3", "NtorQ", 24500.0, False),
    ]
    out = build_invoice_pdf(_invoice(grand_total_zmw=100500.0), bikes=bikes, currency="ZMW")
    assert isinstance(out, bytes) and out[:4] == b"%PDF" and len(out) > 800
