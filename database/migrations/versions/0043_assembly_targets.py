"""assembly targets — per model/colour tuning for the Assembly Planner

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-08

The Assembly Planner recommends which bikes to assemble deterministically from CURRENT
stock (assembled vs unassembled counts). This adds a per model/colour override table so a
tenant can tune the keep-target and thinness threshold; the planner falls back to module
defaults when absent. Additive table only; no data changed. Reuses the existing motorcycle
permissions (no new permission seeded).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "assembly_targets.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assembly_targets;")
