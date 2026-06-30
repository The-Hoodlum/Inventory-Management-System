"""motorcycle lifecycle — serialized-unit registry

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-30

Adds motorcycle_units + motorcycle_unit_events (the per-unit immutable lifecycle
ledger) via the idempotent DDL in sql/motorcycle_units.sql. A generic serialized-asset
registry, distinct from fungible inventory; linked to the existing sales documents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "motorcycle_units.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in ["motorcycle_unit_events", "motorcycle_units"]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
