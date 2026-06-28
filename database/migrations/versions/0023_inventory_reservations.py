"""inventory reservations

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-25

Adds the inventory_reservations table (held stock that reduces qty_available without
moving qty_on_hand) via the idempotent DDL in sql/inventory_reservations.sql. The
running total of active reservations is denormalised onto inventory.qty_reserved by
the application, mirroring how qty_on_hand tracks the stock_movements ledger.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "inventory_reservations.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory_reservations;")
