"""stock transfer ledger (append-only immutable per-line event log)

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-25

Adds the immutable stock_transfer_ledger table via the idempotent DDL in
sql/stock_transfer_ledger.sql (app_user is granted SELECT/INSERT only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "stock_transfer_ledger.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_transfer_ledger;")
