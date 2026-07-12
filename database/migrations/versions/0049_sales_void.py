"""sale void / reverse — invoice void metadata (no hard delete)

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-12

Adds voided_at / voided_by / void_reason to invoices so an admin can reverse a sale
(restoring stock through InventoryService and un-selling a bike) while the document is
kept for audit and excluded from active totals. Additive + idempotent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "sales_void.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS void_reason, "
               "DROP COLUMN IF EXISTS voided_by, DROP COLUMN IF EXISTS voided_at;")
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_status_check;")
    op.execute("ALTER TABLE invoices ADD CONSTRAINT invoices_status_check CHECK ("
               "status IN ('draft', 'sent', 'partially_paid', 'paid', 'overdue', 'cancelled'));")
