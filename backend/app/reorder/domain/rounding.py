"""Full-carton rounding and MOQ enforcement.

These two rules are the heart of the procurement policy:

  FULL CARTON RULE  — never order partial cartons. The quantity is always rounded
                      UP to a whole multiple of ``units_per_carton``.
                      e.g. units_per_carton=10, qty=67  ->  70

  MOQ RULE          — never order below the minimum order quantity. If the
                      cartoned quantity is below the MOQ, raise it to the MOQ
                      (itself rounded up to whole cartons, so the full-carton
                      rule is never violated).
                      e.g. moq=500, qty=320  ->  500
"""
from __future__ import annotations

import math
from decimal import Decimal

from app.reorder.domain.exceptions import InvalidPolicyError
from app.reorder.domain.models import OrderQuantity

ZERO = Decimal("0")


def round_up_to_carton(quantity: Decimal | int, units_per_carton: int) -> int:
    """Round ``quantity`` UP to the nearest whole multiple of ``units_per_carton``.

    Returns whole units (a multiple of units_per_carton). ``quantity`` <= 0 yields 0.
    """
    if units_per_carton < 1:
        raise InvalidPolicyError("units_per_carton must be >= 1")
    q = Decimal(quantity)
    if q <= 0:
        return 0
    cartons = math.ceil(q / Decimal(units_per_carton))
    return cartons * units_per_carton


def enforce_order_quantity(
    raw_quantity: Decimal | int,
    units_per_carton: int,
    moq: int = 0,
) -> OrderQuantity:
    """Apply the full-carton rule then the MOQ rule to a raw order quantity.

    No order is suggested for a non-positive raw quantity (MOQ is only enforced
    once an order is actually warranted).
    """
    if units_per_carton < 1:
        raise InvalidPolicyError("units_per_carton must be >= 1")
    if moq < 0:
        raise InvalidPolicyError("moq must be >= 0")

    raw = Decimal(raw_quantity)
    if raw <= 0:
        return OrderQuantity(
            raw_units=raw if raw > 0 else ZERO,
            cartoned_units=0,
            recommended_units=0,
            cartons=0,
            applied_moq=False,
        )

    cartoned = round_up_to_carton(raw, units_per_carton)
    units = cartoned
    applied_moq = False
    if moq and units < moq:
        units = round_up_to_carton(moq, units_per_carton)
        applied_moq = True

    return OrderQuantity(
        raw_units=raw,
        cartoned_units=cartoned,
        recommended_units=units,
        cartons=units // units_per_carton,
        applied_moq=applied_moq,
    )
