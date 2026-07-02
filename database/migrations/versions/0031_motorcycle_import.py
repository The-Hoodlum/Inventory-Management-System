"""motorcycle bulk import - provenance columns on motorcycle_units

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-02

Additive provenance columns (imported_historical + import_job_id) so bulk-imported
units are traceable to their import job, and historically back-filled sales/holds are
distinguishable from live ones. Registers the ``motorcycle_units`` import target (code
only, no schema). No data is deleted.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "motorcycle_import.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_motorcycle_units_import_job;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS date_sold;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS assembled_date;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS import_job_id;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS imported_historical;")
