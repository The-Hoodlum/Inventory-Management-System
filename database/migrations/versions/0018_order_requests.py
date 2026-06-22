"""order request (branch requisition) system

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-22

Adds request_headers, request_lines, request_audit, the request_counters sequence +
next_request_number(), RLS, and the order_request.* permissions, via the idempotent DDL
in sql/order_requests.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "order_requests.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS request_audit;")
    op.execute("DROP TABLE IF EXISTS request_lines;")
    op.execute("DROP TABLE IF EXISTS request_headers;")
    op.execute("DROP FUNCTION IF EXISTS next_request_number(UUID);")
    op.execute("DROP TABLE IF EXISTS request_counters;")
    op.execute("DELETE FROM permissions WHERE code LIKE 'order_request.%';")
