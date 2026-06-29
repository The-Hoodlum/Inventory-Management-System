"""sales documents (quotation -> sales order -> delivery -> invoice -> payment -> receipt)

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-28

Adds the sales-document spine + per-tenant numbering via the idempotent DDL in
sql/sales_documents.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

_TABLES = [
    "payment_allocations", "payments", "receipts",
    "invoice_lines", "invoices",
    "delivery_note_lines", "delivery_notes",
    "sales_order_lines", "sales_orders",
    "quotation_lines", "quotations",
    "sales_counters",
]


def upgrade() -> None:
    op.execute((SQL_DIR / "sales_documents.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS next_sales_number(uuid, text, text);")
