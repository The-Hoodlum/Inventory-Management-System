"""customer handover — signed record that a customer received their motorcycle

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-08

Adds the customer_handovers table (the paper form's Customer + Internal copies as one
signed row) and two INDEPENDENT lifecycle columns on motorcycle_units — delivered +
delivered_at — mirroring the existing inspected / registered facts. Completing a handover
sets these + stamps warranty_start and writes a 'delivered' unit event, WITHOUT changing
the terminal SOLD sale-status (so sales reporting is unaffected).

Additive only; no data changed. Reuses next_sales_number('handover','HO').
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "customer_handovers.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_handovers;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS delivered_at;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS delivered;")
