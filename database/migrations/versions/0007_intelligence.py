"""supply-chain intelligence data layer

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-13

Adds the ``intelligence_signals`` table (normalised intelligence observations
across freight/port/commodity/trade/supplier/geopolitical categories) by
executing the idempotent DDL in ``sql/intelligence.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "intelligence.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intelligence_signals;")
