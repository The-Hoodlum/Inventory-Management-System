"""product intelligence profile

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-14

Adds the Product Intelligence Profile columns (commodity_tags, country_of_origin,
transport_mode, criticality, supplier_dependency, demand_type, substitutability)
to ``products`` via the idempotent DDL in ``sql/product_profile.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "product_profile.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE products
            DROP COLUMN IF EXISTS commodity_tags,
            DROP COLUMN IF EXISTS country_of_origin,
            DROP COLUMN IF EXISTS transport_mode,
            DROP COLUMN IF EXISTS criticality,
            DROP COLUMN IF EXISTS supplier_dependency,
            DROP COLUMN IF EXISTS demand_type,
            DROP COLUMN IF EXISTS substitutability;
        """
    )
