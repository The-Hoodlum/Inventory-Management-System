"""bike issues — internal bike repairs that consume spare parts

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-07

Record an internal repair on a specific bike we own and consume the spare part(s) used
to fix it. NOT a customer sale: the part is an internal cost. Consumption goes through
the ONE existing inventory write path (InventoryService.issue), tagged
reference_type='bike_repair'. Opening an issue routes the unit to `on_hold` (reusing the
serialized lifecycle); resolving returns it to its prior sellable status. Additive tables
only; no data changed. Reuses next_sales_number('bike_issue').
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "bike_issues.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bike_issue_lines;")
    op.execute("DROP TABLE IF EXISTS bike_issues;")
