"""supplier intelligence scorecards

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-14

Adds the ``supplier_scores`` table (persisted, intelligence-blended supplier
scorecards) via the idempotent DDL in ``sql/supplier_scores.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "supplier_scores.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supplier_scores;")
