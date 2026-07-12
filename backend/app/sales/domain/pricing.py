"""Pure pricing / total math for sales documents (no DB; unit-tested).

VAT is applied per line by the line's TREATMENT (a property of the product type):

  * EXCLUSIVE (spare parts): the unit price is NET; VAT is ADDED on top.
        net = base - discount ; vat = net * rate ; gross(payable) = net + vat
        (a 100 part at 16% -> net 100, VAT 16, gross 116)
  * INCLUSIVE (motorcycles): the unit price is GROSS (already contains VAT); the VAT is
    EXTRACTED, never added.
        gross(payable) = base - discount ; net = gross / (1 + rate) ; vat = gross - net
        (a 20,000 bike at 16% -> gross 20,000, net 17,241.38, VAT 2,758.62; still pays 20,000)

``tax_pct`` is the VAT rate as a PERCENT (16 == 16%). ``gross`` in the returned dict keeps
its legacy meaning (extended price BEFORE discount); ``line_total`` is the payable
(VAT-inclusive) amount. Document totals: subtotal = sum(base), net_total = sum(net),
tax_total = sum(vat), grand_total = sum(payable). Each line is rounded before summing so
``sum(lines) == total`` by construction, whatever the treatment mix.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_Q = Decimal("0.0001")
_ZMW_Q = Decimal("0.01")   # billing currency (ZMW) is quoted to 2 dp (ngwee)
_HUNDRED = Decimal("100")

EXCLUSIVE = "exclusive"
INCLUSIVE = "inclusive"
TREATMENTS = frozenset({EXCLUSIVE, INCLUSIVE})


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _round(v: Decimal) -> Decimal:
    return v.quantize(_Q, rounding=ROUND_HALF_UP)


def normalise_treatment(t) -> str:
    t = str(t or "").strip().lower()
    return t if t in TREATMENTS else EXCLUSIVE


def to_zmw(usd_amount, fx_rate) -> Decimal:
    """Convert a USD amount to the billing currency at ``fx_rate``, rounded to 2 dp
    (ROUND_HALF_UP). Rounding each line the same way and summing line ZMW into the
    document total keeps ``sum(lines) == total`` by construction."""
    return (_d(usd_amount) * _d(fx_rate)).quantize(_ZMW_Q, rounding=ROUND_HALF_UP)


def line_amounts(qty, unit_price, discount_pct=0, tax_pct=0, treatment=EXCLUSIVE) -> dict[str, Decimal]:
    """Return gross(pre-discount) / discount / net / tax / vat / line_total(payable) for
    one line, computed by ``treatment`` (exclusive adds VAT, inclusive extracts it)."""
    qty, price = _d(qty), _d(unit_price)
    disc_pct, rate = _d(discount_pct), _d(tax_pct)
    base = qty * price
    discount = base * disc_pct / _HUNDRED
    taxable = base - discount
    if normalise_treatment(treatment) == INCLUSIVE:
        # Price already contains VAT: extract it, never add.
        payable = taxable
        net = payable / (Decimal("1") + rate / _HUNDRED)
        vat = payable - net
    else:
        # Price is net: add VAT on top.
        net = taxable
        vat = net * rate / _HUNDRED
        payable = net + vat
    return {
        "gross": _round(base),
        "discount": _round(discount),
        "net": _round(net),
        "tax": _round(vat),
        "vat": _round(vat),
        "line_total": _round(payable),
    }


def line_total(qty, unit_price, discount_pct=0, tax_pct=0, treatment=EXCLUSIVE) -> Decimal:
    return line_amounts(qty, unit_price, discount_pct, tax_pct, treatment)["line_total"]


def document_totals(lines: list[dict]) -> dict[str, Decimal]:
    """Aggregate document totals from lines (each: qty/unit_price/discount_pct/tax_pct/
    optional treatment). ``subtotal`` = sum(base); ``net_total`` = sum(net); ``tax_total``
    = sum(VAT); ``grand_total`` = sum(payable). Each line already rounded, so lines sum to
    totals exactly regardless of per-line treatment."""
    subtotal = discount = net = tax = grand = Decimal("0")
    for ln in lines:
        a = line_amounts(
            ln["qty"], ln["unit_price"], ln.get("discount_pct", 0),
            ln.get("tax_pct", 0), ln.get("treatment", EXCLUSIVE),
        )
        subtotal += a["gross"]
        discount += a["discount"]
        net += a["net"]
        tax += a["tax"]
        grand += a["line_total"]
    return {
        "subtotal": _round(subtotal),
        "discount_total": _round(discount),
        "net_total": _round(net),
        "tax_total": _round(tax),
        "grand_total": _round(grand),
    }
