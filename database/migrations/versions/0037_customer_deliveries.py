"""branch -> customer/reseller delivery (sale | consignment) — delivery-note Type 3

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-05

A customer/reseller delivery note in two modes: sale (proof of a sale's handover — no
re-deduction) and consignment (stock held at the reseller, settled as sold / returned if
unsold). Additive tables only; no data changed. Reuses next_sales_number('customer_delivery').
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "customer_deliveries.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_delivery_lines;")
    op.execute("DROP TABLE IF EXISTS customer_deliveries;")
