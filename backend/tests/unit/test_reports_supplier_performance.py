"""Unit tests for supplier-performance aggregation (pure domain, no DB).

Dependency-light (no ``import pytest``) so they run under pytest and a plain
runner alike.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.reports.compute import supplier_performance

NOW = dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.timezone.utc)

S1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
S2 = uuid.UUID("11111111-0000-0000-0000-000000000002")
S3 = uuid.UUID("11111111-0000-0000-0000-000000000003")
S_UNKNOWN = uuid.UUID("99999999-0000-0000-0000-000000000009")

PO1 = uuid.UUID("aaaa0000-0000-0000-0000-000000000001")
PO2 = uuid.UUID("aaaa0000-0000-0000-0000-000000000002")
PO3 = uuid.UUID("aaaa0000-0000-0000-0000-000000000003")
POX = uuid.UUID("aaaa0000-0000-0000-0000-00000000000x".replace("x", "9"))


def dtm(days: int) -> dt.datetime:
    return NOW - dt.timedelta(days=days)


def approx(a, b, tol=1e-9) -> bool:
    return a is not None and abs(a - b) < tol


def _fixture():
    # po1: on-time (received == expected), lead 10d; po2: late, lead 25d. Both S1.
    pos = [
        (PO1, S1, "received", dtm(10).date(), dtm(25)),
        (PO2, S1, "received", dtm(8).date(), dtm(35)),
        (PO3, S2, "sent", None, dtm(4)),
        (POX, S_UNKNOWN, "received", dtm(1).date(), dtm(2)),  # ignored: not in set
    ]
    line_totals = {
        PO1: (Decimal("100"), Decimal("100")),
        PO2: (Decimal("50"), Decimal("25")),
        PO3: (Decimal("10"), Decimal("4")),
        POX: (Decimal("1000"), Decimal("1000")),
    }
    timestamps = {
        PO1: {"sent": dtm(20), "received": dtm(10)},
        PO2: {"sent": dtm(30), "received": dtm(5)},  # received (5d ago) after expected (8d ago) => late
        PO3: {"sent": dtm(3)},
    }
    return pos, line_totals, timestamps


def test_supplier_with_mixed_receipts():
    pos, line_totals, timestamps = _fixture()
    calc = supplier_performance([S1, S2, S3], pos, line_totals, timestamps)
    c1 = calc[S1]
    assert c1.po_count == 2
    assert c1.received_po_count == 2
    assert c1.on_time_po_count == 1
    assert approx(c1.on_time_rate, 0.5)
    assert approx(c1.avg_lead_time_days, 17.5)  # (10 + 25) / 2
    assert approx(c1.fill_rate, 125 / 150)      # (100+25) / (100+50)
    assert c1.last_order_at == dtm(25)          # most recent created_at


def test_supplier_sent_not_received():
    pos, line_totals, timestamps = _fixture()
    calc = supplier_performance([S1, S2, S3], pos, line_totals, timestamps)
    c2 = calc[S2]
    assert c2.po_count == 1
    assert c2.received_po_count == 0
    assert c2.on_time_rate is None
    assert c2.avg_lead_time_days is None
    assert approx(c2.fill_rate, 0.4)  # 4 / 10
    assert c2.last_order_at == dtm(4)


def test_supplier_with_no_pos():
    pos, line_totals, timestamps = _fixture()
    calc = supplier_performance([S1, S2, S3], pos, line_totals, timestamps)
    c3 = calc[S3]
    assert c3.po_count == 0
    assert c3.received_po_count == 0
    assert c3.on_time_rate is None
    assert c3.avg_lead_time_days is None
    assert c3.fill_rate is None
    assert c3.last_order_at is None


def test_unknown_supplier_is_ignored():
    pos, line_totals, timestamps = _fixture()
    calc = supplier_performance([S1, S2, S3], pos, line_totals, timestamps)
    assert S_UNKNOWN not in calc


def test_lead_time_falls_back_to_created_when_no_sent():
    sid = S1
    po = uuid.UUID("cccc0000-0000-0000-0000-000000000001")
    pos = [(po, sid, "received", None, dtm(15))]
    timestamps = {po: {"received": dtm(5)}}  # no 'sent' -> base is created_at (15d)
    calc = supplier_performance([sid], pos, {}, timestamps)
    assert approx(calc[sid].avg_lead_time_days, 10.0)  # 15 - 5


def test_cancelled_and_draft_excluded_from_fill():
    sid = S1
    a = uuid.UUID("dddd0000-0000-0000-0000-000000000001")
    b = uuid.UUID("dddd0000-0000-0000-0000-000000000002")
    pos = [
        (a, sid, "cancelled", None, dtm(2)),
        (b, sid, "draft", None, dtm(1)),
    ]
    line_totals = {a: (Decimal("100"), Decimal("0")), b: (Decimal("50"), Decimal("0"))}
    calc = supplier_performance([sid], pos, line_totals, {})
    assert calc[sid].po_count == 2
    assert calc[sid].received_po_count == 0
    assert calc[sid].fill_rate is None  # no active POs contributed an ordered qty
