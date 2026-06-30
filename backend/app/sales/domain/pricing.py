"""Pure pricing / total math for sales documents (no DB; unit-tested).

Per line:  gross = qty * unit_price; discount = gross * discount_pct/100;
           net = gross - discount; tax = net * tax_pct/100; line_total = net + tax.
Document:  subtotal = sum(gross); discount_total = sum(discount);
           tax_total = sum(tax); grand_total = subtotal - discount_total + tax_total.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_Q = Decimal("0.0001")
_HUNDRED = Decimal("100")


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _round(v: Decimal) -> Decimal:
    return v.quantize(_Q, rounding=ROUND_HALF_UP)


def line_amounts(qty, unit_price, discount_pct=0, tax_pct=0) -> dict[str, Decimal]:
    """Return gross / discount / net / tax / line_total for one line."""
    qty, price = _d(qty), _d(unit_price)
    disc_pct, tax_pct = _d(discount_pct), _d(tax_pct)
    gross = qty * price
    discount = gross * disc_pct / _HUNDRED
    net = gross - discount
    tax = net * tax_pct / _HUNDRED
    return {
        "gross": _round(gross),
        "discount": _round(discount),
        "net": _round(net),
        "tax": _round(tax),
        "line_total": _round(net + tax),
    }


def line_total(qty, unit_price, discount_pct=0, tax_pct=0) -> Decimal:
    return line_amounts(qty, unit_price, discount_pct, tax_pct)["line_total"]


def document_totals(lines: list[dict]) -> dict[str, Decimal]:
    """Aggregate document totals from lines (each: qty/unit_price/discount_pct/tax_pct)."""
    subtotal = discount = tax = grand = Decimal("0")
    for ln in lines:
        a = line_amounts(ln["qty"], ln["unit_price"], ln.get("discount_pct", 0), ln.get("tax_pct", 0))
        subtotal += a["gross"]
        discount += a["discount"]
        tax += a["tax"]
        grand += a["line_total"]
    return {
        "subtotal": _round(subtotal),
        "discount_total": _round(discount),
        "tax_total": _round(tax),
        "grand_total": _round(grand),
    }
