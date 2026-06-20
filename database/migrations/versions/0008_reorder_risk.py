"""risk overlay on reorder recommendations

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-13

Adds risk columns (risk_score, lead_time_extra_days, risk_cost_impact, expedite,
risk_drivers) to ``reorder_recommendations`` via the idempotent DDL in
``sql/reorder_risk.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "reorder_risk.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE reorder_recommendations
            DROP COLUMN IF EXISTS risk_score,
            DROP COLUMN IF EXISTS lead_time_extra_days,
            DROP COLUMN IF EXISTS risk_cost_impact,
            DROP COLUMN IF EXISTS expedite,
            DROP COLUMN IF EXISTS risk_drivers;
        """
    )
