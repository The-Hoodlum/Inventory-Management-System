"""wholesale price on products

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-05

Adds products.wholesale_price (a third price tier alongside cost + selling/retail). Additive
and defaulted; existing rows/writers/readers unaffected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "product_wholesale_price.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS wholesale_price;")
