"""parts sales history — imported spare-part sales (Sales Log)

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-12

Adds parts_sales: the record-only history of imported spare-part sales (the "Sales Log"
spreadsheet). Never writes stock; the Sales Log report unions it into parts revenue
alongside live invoice_lines. Additive + idempotent; no data changed. Reuses report.read
to view and data.import to load (no new permission seeded).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "parts_sales.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS parts_sales;")
