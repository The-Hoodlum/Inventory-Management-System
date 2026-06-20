"""purchase order events timeline

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-10

Adds the ``purchase_order_events`` table (PO lifecycle timeline with approval
comments and receipt details) by executing the idempotent DDL in
``sql/po_events.sql``. Idempotent, so it is safe even if the table was already
created by the fresh-init scripts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "po_events.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS purchase_order_events;")
