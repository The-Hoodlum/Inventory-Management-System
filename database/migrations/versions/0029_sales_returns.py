"""sales returns + credit notes

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-29

Adds returns / return_lines / credit_notes / credit_note_lines, invoices.credit_total,
and the sales.return permission via the idempotent DDL in sql/sales_returns.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "sales_returns.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in ["credit_note_lines", "credit_notes", "return_lines", "returns"]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS credit_total;")
