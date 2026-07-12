"""parts_sales_log import target — plan() validation + valuation.

Guarantees: date + qty required; revenue taken from the sheet's Total (ZMW) when present
(and the effective fx backed out), else computed from price x qty x fx; an item code not
in the catalog is NOT an error (recorded with a null product link); bad rows error without
blocking the good ones.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.imports.domain.validation import validate_mapped
from app.imports.targets.parts_sales_log import DEFAULT_FX, PartsSalesLogImporter


class _FakeSession:
    """Stands in for the DB session — no product ever resolves (null product_id path)."""

    async def scalar(self, *_a, **_k):
        return None


def _rows(imp, raw_rows):
    out = []
    for i, raw in enumerate(raw_rows, start=2):
        clean, ferrs = validate_mapped(imp.fields, raw)
        out.append((i, clean, ferrs))
    return out


@pytest.mark.asyncio
async def test_plan_values_and_validates():
    imp = PartsSalesLogImporter()
    raw = [
        # good: total present -> revenue = total, fx backed out (257.4 / (4.29*3) = 20)
        {"date": "2026-04-23", "item_code": "TR600285FB", "qty": "3",
         "unit_price_usd": "4.29", "total_zmw": "257.4", "vat_zmw": "298.58", "customer": "Walk-in"},
        # good: no total -> compute price*qty*DEFAULT_FX
        {"date": "2026-05-01", "item_code": "K6011090", "qty": "2", "unit_price_usd": "1.00"},
        # bad: missing date
        {"date": "", "item_code": "X", "qty": "1", "unit_price_usd": "1"},
        # bad: qty zero
        {"date": "2026-05-02", "item_code": "Y", "qty": "0", "unit_price_usd": "1"},
        # bad: no value basis (no total, no price)
        {"date": "2026-05-03", "item_code": "Z", "qty": "1"},
    ]
    plan = await imp.plan(_FakeSession(), tenant_id="t", rows=_rows(imp, raw))
    ok = [r for r in plan.rows if r.ok]
    bad = [r for r in plan.rows if not r.ok]
    assert len(ok) == 2 and len(bad) == 3

    r0 = plan.rows[0]
    assert r0.data["revenue_zmw"] == Decimal("257.4")
    assert r0.data["fx_rate"] == Decimal("20.000000")
    assert r0.data["product_id"] is None          # unmatched code still recorded
    assert r0.data["sale_date"] == dt.date(2026, 4, 23)

    r1 = plan.rows[1]
    assert r1.data["revenue_zmw"] == Decimal("1.00") * Decimal("2") * DEFAULT_FX

    assert any("Date is required" in e for e in plan.rows[2].errors)
    assert any("greater than zero" in e for e in plan.rows[3].errors)
    assert any("Total (ZMW) or a Unit Price" in e for e in plan.rows[4].errors)


@pytest.mark.asyncio
async def test_commit_inserts_one_per_valid_row():
    imp = PartsSalesLogImporter()
    raw = [
        {"date": "2026-04-23", "item_code": "A", "qty": "1", "total_zmw": "20"},
        {"date": "bad", "item_code": "B", "qty": "1", "total_zmw": "20"},
    ]
    plan = await imp.plan(_FakeSession(), tenant_id="t", rows=_rows(imp, raw))

    added = []

    class _S:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
            pass

    created = await imp.commit(_S(), tenant_id="t", user_id="u", job_id="j", plan=plan)
    assert created == 1 and len(added) == 1
