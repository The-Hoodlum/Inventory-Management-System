"""VAT — configurable tenant rate + per-line treatment, net/vat/gross frozen on documents

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-12

Gives tenants.vat_rate a 16% default (+ backfill), adds products.vat_treatment, and
freezes net/vat + the treatment/rate applied on every sales-document line and total.
Additive + idempotent; no stock touched.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "vat.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for t in ("quotation_lines", "sales_order_lines", "invoice_lines", "credit_note_lines"):
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS net_amount, DROP COLUMN IF EXISTS vat_amount, "
                   f"DROP COLUMN IF EXISTS vat_treatment, DROP COLUMN IF EXISTS vat_rate;")
    for t in ("quotations", "sales_orders", "invoices", "credit_notes"):
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS net_total, DROP COLUMN IF EXISTS vat_rate;")
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_vat_treatment_ck;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS vat_treatment;")
