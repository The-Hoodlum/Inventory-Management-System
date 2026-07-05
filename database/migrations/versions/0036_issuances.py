"""internal issuance / handover (out-and-back loan) — delivery-note Type 4

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-04

Issue a bike and/or items on loan, then get them back. Never sells or permanently
deducts returnable stock: bikes are marked out-on-loan (derived availability), fungible
items are HELD via the reservation mechanism, consumables are deducted at handover.
Additive tables only; no data changed. Reuses next_sales_number('issuance').
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "issuances.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS issuance_lines;")
    op.execute("DROP TABLE IF EXISTS issuances;")
