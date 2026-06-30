"""customers + sales/POS RBAC foundation

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-28

Adds customers / customer_addresses and the shared sales permission + role
foundation (Salesperson, Finance roles; customer.*/sales.*/pos.* permissions)
via the idempotent DDL in sql/customers.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "customers.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_addresses;")
    op.execute("DROP TABLE IF EXISTS customers;")
    op.execute("DROP TABLE IF EXISTS customer_counters;")
    op.execute("DROP FUNCTION IF EXISTS next_customer_number(uuid);")
