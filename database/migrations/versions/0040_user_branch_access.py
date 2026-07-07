"""user -> branch scoping (user_branch_access)

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-06

Additive user->branch grant table for server-side branch isolation. No rows for a user =
unrestricted (all branches). Existing data/writers/readers unaffected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "user_branch_access.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_branch_access;")
