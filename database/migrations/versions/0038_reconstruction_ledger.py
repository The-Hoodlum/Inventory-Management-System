"""reconstruction support on the stock ledger (occurred_at + imported_historical)

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-05

Additive columns on stock_movements for history reconstruction: occurred_at (back-dated
business moment) and imported_historical (reconstructed-not-live flag), plus the
'opening_balance' movement type. No existing data changed; all writers/readers unaffected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "reconstruction.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_movements_product_occurred;")
    op.execute("ALTER TABLE stock_movements DROP COLUMN IF EXISTS imported_historical;")
    op.execute("ALTER TABLE stock_movements DROP COLUMN IF EXISTS occurred_at;")
    # Restore the movement_type check without 'opening_balance'.
    op.execute("ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_movement_type_check;")
    op.execute(
        "ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_movement_type_check "
        "CHECK (movement_type IN "
        "('receipt','issue','adjustment','transfer_in','transfer_out',"
        "'damage','reserve','unreserve','initial_import'));"
    )
