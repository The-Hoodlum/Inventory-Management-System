"""motorcycle module - serialized-asset catalog + per-unit registry

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-01

Adds the two-layer Motorcycle module via the idempotent DDL in
sql/motorcycle_units.sql:

  Layer 1 (reference catalog): motorcycle_models, motorcycle_variants,
                               motorcycle_colours
  Layer 2 (per-unit registry): motorcycle_units + motorcycle_unit_events

plus the motorcycle.* permissions and their role grants. Selling a unit links to
the existing sales documents (reserved_ref -> sales_orders, sold_ref -> invoices);
there is no parallel sales path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "motorcycle_units.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS motorcycle_unit_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS motorcycle_units       CASCADE;")
    op.execute("DROP TABLE IF EXISTS motorcycle_variants    CASCADE;")
    op.execute("DROP TABLE IF EXISTS motorcycle_colours     CASCADE;")
    op.execute("DROP TABLE IF EXISTS motorcycle_models      CASCADE;")
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('motorcycle.read','motorcycle.manage','motorcycle.config');"
    )
