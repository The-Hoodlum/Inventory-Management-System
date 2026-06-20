"""product intelligence profile: strategic flags

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-20

Adds ``products.strategic_item`` and ``products.alternate_supplier_available``
(booleans) via the idempotent DDL in ``sql/product_profile_flags.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "product_profile_flags.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS strategic_item;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS alternate_supplier_available;")
