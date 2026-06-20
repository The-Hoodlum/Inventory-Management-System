"""seed rbac reference data

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-09

Loads the permission catalog, the five built-in system roles, and their
permission mappings (idempotent). These RBAC tables are not under RLS, so no
tenant GUC is required.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    seed_sql = (SQL_DIR / "seed_rbac.sql").read_text(encoding="utf-8")
    op.execute(seed_sql)


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE is_system);
        DELETE FROM roles WHERE is_system;
        DELETE FROM permissions;
        """
    )
