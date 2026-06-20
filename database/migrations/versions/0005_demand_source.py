"""demand source tagging on sales_daily

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-13

Adds the ``source`` column to ``sales_daily`` and widens its uniqueness key to
(product, warehouse, date, source) by executing the idempotent DDL in
``sql/demand_source.sql``. Safe to run even if the fresh-init scripts already
applied it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "demand_source.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE sales_daily DROP CONSTRAINT IF EXISTS uq_sales_daily_pwds;
        ALTER TABLE sales_daily DROP COLUMN IF EXISTS source;
        ALTER TABLE sales_daily
            ADD CONSTRAINT sales_daily_product_id_warehouse_id_sale_date_key
            UNIQUE (product_id, warehouse_id, sale_date);
        """
    )
