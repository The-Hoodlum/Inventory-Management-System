"""finance_payment_mapping — per-branch payment-method -> account mapping (money-in)

Revision ID: 0056
Revises: 0055
Create Date: 2026-07-19

PR 2 of the finance module. Additive config table ``finance_payment_account_map`` that
maps a sales payment method to a finance account per branch, so recorded invoice payments
auto-post one IN movement each. No data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "finance_payment_mapping.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS finance_payment_account_map;")
