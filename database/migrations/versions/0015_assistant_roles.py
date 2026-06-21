"""assistant front-line roles (branch manager / cashier / mechanic)

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-21

Adds the three assistant front-line system roles and their grants via the idempotent
DDL in ``sql/assistant_roles.sql``. The per-tool limits are enforced in code
(app/assistant/domain/capabilities.py); these grants just enable sign-in + read APIs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "assistant_roles.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    # Remove the three roles (role_permissions cascade via FK).
    op.execute(
        "DELETE FROM roles WHERE is_system AND name IN ('Branch Manager', 'Cashier', 'Mechanic');"
    )
