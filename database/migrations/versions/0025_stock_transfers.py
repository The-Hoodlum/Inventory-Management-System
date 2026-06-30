"""stock transfers (full transfer lifecycle on the order-request tables)

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-25

Extends request_headers / request_lines to the full transfer lifecycle (new
statuses + transfer types, header received_by/received_date, line extra_qty and
the reconciliation invariant, and the order_request.receive permission) via the
idempotent DDL in sql/stock_transfers.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "stock_transfers.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE request_lines DROP CONSTRAINT IF EXISTS request_lines_reconcile_check;")
    op.execute("ALTER TABLE request_lines DROP COLUMN IF EXISTS extra_qty;")
    op.execute("ALTER TABLE request_headers DROP COLUMN IF EXISTS received_by;")
    op.execute("ALTER TABLE request_headers DROP COLUMN IF EXISTS received_date;")
