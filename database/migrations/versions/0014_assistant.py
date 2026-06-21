"""conversational assistant (whatsapp/openai)

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-20

Adds assistant_conversations, assistant_messages, user_warehouse_access, and
whatsapp_identities, plus the assistant.use permission, via the idempotent DDL in
``sql/assistant.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "assistant.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_messages;")
    op.execute("DROP TABLE IF EXISTS assistant_conversations;")
    op.execute("DROP TABLE IF EXISTS user_warehouse_access;")
    op.execute("DROP TABLE IF EXISTS whatsapp_identities;")
    op.execute("DELETE FROM permissions WHERE code = 'assistant.use';")
