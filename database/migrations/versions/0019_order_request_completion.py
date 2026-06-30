"""order request completion (receipt confirmation) + cancellation

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-24

Adds the terminal 'completed' status, receipt-confirmation columns, per-line
discrepancy capture, and the order_request.complete permission, via the idempotent
DDL in sql/order_request_completion.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "order_request_completion.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE request_lines DROP COLUMN IF EXISTS received_qty;")
    op.execute("ALTER TABLE request_lines DROP COLUMN IF EXISTS missing_qty;")
    op.execute("ALTER TABLE request_lines DROP COLUMN IF EXISTS damaged_qty;")
    op.execute("ALTER TABLE request_headers DROP COLUMN IF EXISTS completed_by;")
    op.execute("ALTER TABLE request_headers DROP COLUMN IF EXISTS completed_date;")
    op.execute("ALTER TABLE request_headers DROP COLUMN IF EXISTS completion_remarks;")
    op.execute("ALTER TABLE request_headers DROP CONSTRAINT IF EXISTS request_headers_status_check;")
    op.execute(
        "ALTER TABLE request_headers ADD CONSTRAINT request_headers_status_check "
        "CHECK (status IN ('pending','approved','partially_approved','rejected','issued','cancelled'));"
    )
    op.execute("DELETE FROM permissions WHERE code = 'order_request.complete';")
