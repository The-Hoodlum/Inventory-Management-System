"""order_request.transfer permission (per-type role gating)

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-07

Adds the order_request.transfer permission (raise an inter-location transfer) and grants it
to stock-manager roles. Additive; a cashier keeps order_request.create (restock only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "order_request_transfer_permission.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code = 'order_request.transfer';")
