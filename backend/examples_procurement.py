"""Runnable, dependency-free demonstration of the procurement domain core.

    python examples_procurement.py

Exercises the state machine (valid + blocked transitions) and goods receiving
(full / partial / multiple / over-receipt) using only the pure domain — no
FastAPI, no database.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.procurement.domain.exceptions import InvalidTransitionError, ReceiptError
from app.procurement.domain.receiving import LineState, apply_receipt
from app.procurement.domain.states import POAction, POStatus, assert_transition, can_transition

LINE = "-" * 78


def _state_machine_demo() -> None:
    print(LINE)
    print("STATE MACHINE")
    print(LINE)

    happy = [
        (POStatus.DRAFT, POAction.SUBMIT),
        (POStatus.PENDING_APPROVAL, POAction.APPROVE),
        (POStatus.APPROVED, POAction.SEND),
        (POStatus.SENT, POAction.RECEIVE),
        (POStatus.PARTIALLY_RECEIVED, POAction.RECEIVE),
    ]
    for current, action in happy:
        ok = can_transition(current, action)
        print(f"  allow  {current.value:<20} --{action.value:<8}-> {ok}")

    print("  blocked transitions:")
    blocked = [
        (POStatus.DRAFT, POAction.APPROVE),
        (POStatus.APPROVED, POAction.APPROVE),
        (POStatus.RECEIVED, POAction.CANCEL),
        (POStatus.CANCELLED, POAction.SUBMIT),
        (POStatus.REJECTED, POAction.SEND),
        (POStatus.SENT, POAction.CANCEL),
    ]
    for current, action in blocked:
        try:
            assert_transition(current, action)
            print(f"    !! UNEXPECTEDLY ALLOWED {current.value} --{action.value}->")
        except InvalidTransitionError as exc:
            print(f"    {current.value:<20} --{action.value:<8}->  blocked ({exc})")
    print()


def _receiving_demo() -> None:
    print(LINE)
    print("GOODS RECEIVING")
    print(LINE)

    line_a = uuid.uuid4()
    prod_a = uuid.uuid4()

    # Full receipt: ordered 1000, receive 1000 -> received
    states = [LineState(line_a, prod_a, Decimal(1000), Decimal(0))]
    out = apply_receipt(states, {line_a: Decimal(1000)})
    print(f"  FULL    : ordered 1000, received 1000 -> status={out.resulting_status.value}, "
          f"fully={out.fully_received}")

    # Partial receipt: ordered 1000, receive 600 -> partially_received (remaining 400)
    states = [LineState(line_a, prod_a, Decimal(1000), Decimal(0))]
    out = apply_receipt(states, {line_a: Decimal(600)})
    print(f"  PARTIAL : ordered 1000, received 600  -> status={out.resulting_status.value}, "
          f"line_total={out.lines[0].new_received_total}, fully={out.fully_received}")

    # Second receipt against same PO: already 600, receive remaining 400 -> received
    states = [LineState(line_a, prod_a, Decimal(1000), Decimal(600))]
    out = apply_receipt(states, {line_a: Decimal(400)})
    print(f"  2ND RCPT: already 600, received 400    -> status={out.resulting_status.value}, "
          f"line_total={out.lines[0].new_received_total}, fully={out.fully_received}")

    # Multi-line PO, one line completed, the other partial -> partially_received
    line_b = uuid.uuid4()
    prod_b = uuid.uuid4()
    states = [
        LineState(line_a, prod_a, Decimal(100), Decimal(0)),
        LineState(line_b, prod_b, Decimal(50), Decimal(0)),
    ]
    out = apply_receipt(states, {line_a: Decimal(100), line_b: Decimal(20)})
    print(f"  MULTI   : A 100/100, B 20/50           -> status={out.resulting_status.value}, "
          f"received_now={out.total_received_now}")

    # Over-receipt rejected
    states = [LineState(line_a, prod_a, Decimal(1000), Decimal(600))]
    try:
        apply_receipt(states, {line_a: Decimal(500)})
        print("    !! UNEXPECTEDLY ALLOWED over-receipt")
    except ReceiptError as exc:
        print(f"  OVER    : receiving 500 with 400 remaining -> blocked ({exc})")

    # Unknown line rejected
    try:
        apply_receipt(states, {uuid.uuid4(): Decimal(10)})
        print("    !! UNEXPECTEDLY ALLOWED unknown line")
    except ReceiptError:
        print("  UNKNOWN : receipt against unknown line     -> blocked")

    # Non-positive quantity rejected
    try:
        apply_receipt(states, {line_a: Decimal(0)})
        print("    !! UNEXPECTEDLY ALLOWED zero qty")
    except ReceiptError:
        print("  ZERO    : receiving 0 units               -> blocked")
    print()


def main() -> None:
    _state_machine_demo()
    _receiving_demo()


if __name__ == "__main__":
    main()
