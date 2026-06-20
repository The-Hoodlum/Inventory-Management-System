"""import framework phase 2: rolled_back job status

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-19

Extends the ``import_jobs.status`` CHECK with ``'rolled_back'`` so a completed
import can be reversed. Idempotent DDL in ``sql/import_rollback.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "import_rollback.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("UPDATE import_jobs SET status = 'completed' WHERE status = 'rolled_back';")
    op.execute("ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_status_check;")
    op.execute(
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_status_check "
        "CHECK (status IN ('pending','running','completed','cancelled','failed'));"
    )
