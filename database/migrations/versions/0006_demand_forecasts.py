"""demand forecasts persistence

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-13

Adds the ``demand_forecasts`` table (stored forecasts + risk score for accuracy
tracking and the dashboard) by executing the idempotent DDL in
``sql/demand_forecasts.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "demand_forecasts.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS demand_forecasts;")
