"""tenant branding colors

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-22

Adds tenants.branding_colors (JSONB) via the idempotent DDL in sql/tenant_branding.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "tenant_branding.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS branding_colors;")
