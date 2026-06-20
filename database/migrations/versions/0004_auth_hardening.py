"""auth hardening: login lockout + refresh sessions

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-12

Adds login-lockout counters to ``users`` and the ``refresh_sessions`` table by
executing the idempotent DDL in ``sql/auth_hardening.sql``. Safe to run even if
the fresh-init schema already created them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "auth_hardening.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_sessions;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS failed_login_count;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS locked_until;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_failed_login_at;")
