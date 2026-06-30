"""order request source -> destination transfers

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-24

Adds request_headers.destination_branch_id (nullable) so a branch_transfer request
can move stock from its source branch to a destination location, via the idempotent
DDL in sql/order_request_transfers.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "order_request_transfers.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_req_destination;")
    op.execute("ALTER TABLE request_headers DROP COLUMN IF EXISTS destination_branch_id;")
