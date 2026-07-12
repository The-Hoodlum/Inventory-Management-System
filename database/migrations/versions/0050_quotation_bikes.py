"""bike lines in quotations — quotation_lines.unit_id + nullable product_id

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-12

Lets a quotation line quote a serialized motorcycle (unit_id) instead of a product, so a
single quote can mix bikes and parts. product_id becomes nullable; exactly one of
product_id / unit_id identifies the line. Additive + idempotent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "quotation_bikes.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE quotation_lines DROP CONSTRAINT IF EXISTS quotation_lines_part_or_bike_ck;")
    op.execute("ALTER TABLE quotation_lines DROP COLUMN IF EXISTS unit_id;")
    op.execute("ALTER TABLE quotation_lines ALTER COLUMN product_id SET NOT NULL;")
