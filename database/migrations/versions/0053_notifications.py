"""notifications — event-driven, per-recipient in-app notifications

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-15

A generic core: a producer emits an event, recipients are resolved by role/permission +
branch, and one row is stored per recipient (personal read/unread). Separate from the
computed operational signals the bell already shows; the bell merges both. Additive table
only; no data changed. Shipped inert — no producer writes here yet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "notifications.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications;")
