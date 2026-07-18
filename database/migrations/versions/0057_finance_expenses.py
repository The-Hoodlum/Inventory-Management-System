"""finance_expenses — expenses + categories + receipt attachments (money out)

Revision ID: 0057
Revises: 0056
Create Date: 2026-07-19

PR 3 of the finance module. Additive tables: expense_categories (configurable list),
expenses (each posts an OUT movement to its account), and expense_attachments (receipt
bytes in-DB). Manager-recorded, no approval; corrections are voids (reversals), never
deletes. No data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "finance_expenses.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_attachments;")
    op.execute("DROP TABLE IF EXISTS expenses;")
    op.execute("DROP TABLE IF EXISTS expense_categories;")
