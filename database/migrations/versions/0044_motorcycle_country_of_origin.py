"""country of origin on motorcycle units

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-09

Adds motorcycle_units.country_of_origin (free text) so same-model units sourced from
different countries (e.g. India vs Congo) are distinguished per chassis without duplicating
the model. Additive + idempotent; no data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "motorcycle_country_of_origin.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS country_of_origin;")
