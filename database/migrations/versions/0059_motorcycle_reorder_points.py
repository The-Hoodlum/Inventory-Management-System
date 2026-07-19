"""motorcycle_reorder_points — sellable-stock thresholds per model/colour

Revision ID: 0059
Revises: 0058
Create Date: 2026-07-19

The reorder engine covers parts only (products with a reorder_point). Motorcycles are
serialized units with no inventory row, so nothing flagged a model/colour running out.
This additive table adds a per model (optionally per colour) threshold that drives the
"bike colours running low" alert. No data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "motorcycle_reorder_points.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS motorcycle_reorder_points;")
