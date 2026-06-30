"""branches (first-class branch entity)

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-25

Adds the tenant-scoped ``branches`` table and ``warehouses.branch_id`` via the
idempotent DDL in sql/branches.sql, and backfills every existing location onto a
branch (one per distinct ``warehouses.branch`` label; label-less locations attach
to a per-tenant default "Main Branch").
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "branches.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS branch_id;")
    op.execute("DROP TABLE IF EXISTS branches;")
