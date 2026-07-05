"""delivery / dispatch notes (typed) — Type 1 warehouse -> branch transfer

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-04

A typed delivery-note document that DOCUMENTS a stock movement (it never mutates stock
itself — the movement goes through the existing InventoryService for parts and the
serialized motorcycle registry for bikes). Type 1 is a warehouse -> branch transfer with
confirm-on-receipt + per-line discrepancy. Additive tables only; no data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "dispatch_notes.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dispatch_note_lines;")
    op.execute("DROP TABLE IF EXISTS dispatch_notes;")
