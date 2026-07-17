"""notification_prefs — per-user notification channel preferences

Revision ID: 0054
Revises: 0053
Create Date: 2026-07-17

In-app notifications are always delivered; this table governs the opt-in side channels
(today: the WhatsApp push of critical events). Sparse — a user with no row uses the
defaults. Additive table only; no data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "notification_prefs.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_prefs;")
