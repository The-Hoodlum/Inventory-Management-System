"""finance_accounts — finance accounts + append-only account movement ledger

Revision ID: 0055
Revises: 0054
Create Date: 2026-07-18

PR 1 of the finance (cash book / treasury) module. Two additive tables:
``financial_accounts`` (cash / bank / mobile money / custody) and the immutable,
append-only ``account_movements`` ledger. A balance is always DERIVED
(opening_balance + sum(IN) - sum(OUT)), never stored or set. No data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "finance_accounts.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_movements;")
    op.execute("DROP TABLE IF EXISTS financial_accounts;")
