"""product storage location (bin/shelf)

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-09

Adds products.location (free text) so spare parts can be physically located. Additive +
idempotent; no data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "product_location.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS location;")
