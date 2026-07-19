"""finance_transfers_handovers — account transfers + cash handovers

Revision ID: 0058
Revises: 0057
Create Date: 2026-07-19

PR 4 of the finance module. Additive tables: account_transfers (paired OUT+IN),
cash_handovers (two-sided: OUT on record, IN on confirm; discrepancy handling), and
cash_handover_attachments (signed-slip photo in-DB). No data changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "finance_transfers_handovers.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cash_handover_attachments;")
    op.execute("DROP TABLE IF EXISTS cash_handovers;")
    op.execute("DROP TABLE IF EXISTS account_transfers;")
