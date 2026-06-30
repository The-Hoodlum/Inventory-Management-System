"""order request extended purposes (branch_transfer, stock_adjustment)

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-24

Widens request_headers.purpose to include branch_transfer and stock_adjustment,
via the idempotent DDL in sql/order_request_purposes.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "order_request_purposes.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE request_headers DROP CONSTRAINT IF EXISTS request_headers_purpose_check;")
    op.execute(
        "ALTER TABLE request_headers ADD CONSTRAINT request_headers_purpose_check "
        "CHECK (purpose IN ('for_sale','shelf_replenishment','workshop_use','office_use','other'));"
    )
