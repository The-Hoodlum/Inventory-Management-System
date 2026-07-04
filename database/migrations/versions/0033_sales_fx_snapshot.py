"""snapshot USD->billing FX rate + ZMW amounts on sales documents

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-03

Freezes the USD->billing-currency (e.g. ZMW) conversion onto each quotation and
invoice at issue: the rate in effect is snapshotted (``fx_rate``) and the billed
ZMW amounts are stored per line (``line_total_zmw``) and per document
(``grand_total_zmw``). USD stays the source of truth; ZMW is derived and STORED, never
recomputed at view time — so editing the current tenant rate never re-prices an issued
document.

Additive columns only. Existing rows default to fx_rate 1 and are backfilled so their
ZMW equals their USD (a 1:1 identity at rate 1 — NOT a re-price). No data is deleted.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Document-level: frozen rate + billed ZMW grand total.
    op.execute("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18,6) NOT NULL DEFAULT 1;")
    op.execute("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS grand_total_zmw NUMERIC(18,4) NOT NULL DEFAULT 0;")
    op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18,6) NOT NULL DEFAULT 1;")
    op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS grand_total_zmw NUMERIC(18,4) NOT NULL DEFAULT 0;")
    # Line-level: billed ZMW per line (line sums == document total by construction).
    op.execute("ALTER TABLE quotation_lines ADD COLUMN IF NOT EXISTS line_total_zmw NUMERIC(18,4) NOT NULL DEFAULT 0;")
    op.execute("ALTER TABLE invoice_lines ADD COLUMN IF NOT EXISTS line_total_zmw NUMERIC(18,4) NOT NULL DEFAULT 0;")

    # Backfill: pre-existing documents keep fx_rate 1, so ZMW == USD (identity, not a
    # re-price). This makes historical invoices payable in ZMW at their 1:1 value.
    op.execute("UPDATE quotations SET grand_total_zmw = grand_total WHERE grand_total_zmw = 0;")
    op.execute("UPDATE invoices SET grand_total_zmw = grand_total WHERE grand_total_zmw = 0;")
    op.execute("UPDATE quotation_lines SET line_total_zmw = line_total WHERE line_total_zmw = 0;")
    op.execute("UPDATE invoice_lines SET line_total_zmw = line_total WHERE line_total_zmw = 0;")


def downgrade() -> None:
    op.execute("ALTER TABLE invoice_lines DROP COLUMN IF EXISTS line_total_zmw;")
    op.execute("ALTER TABLE quotation_lines DROP COLUMN IF EXISTS line_total_zmw;")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS grand_total_zmw;")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS fx_rate;")
    op.execute("ALTER TABLE quotations DROP COLUMN IF EXISTS grand_total_zmw;")
    op.execute("ALTER TABLE quotations DROP COLUMN IF EXISTS fx_rate;")
