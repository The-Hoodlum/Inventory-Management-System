"""fx rate default for new tenants (USD -> billing currency)

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-03

The USD->local exchange rate lives on ``tenants.fx_rate`` (already present). This
raises the DEFAULT for NEWLY created tenants from 1 to 20 so a fresh tenant starts
with a sensible USD->ZMW placeholder the admin then edits. Existing tenant rows are
NOT touched — changing the current rate is an operational step the admin performs in
Settings, and it must never retroactively re-price issued documents. Purely a column
default change; no data is modified or deleted.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN fx_rate SET DEFAULT 20;")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN fx_rate SET DEFAULT 1;")
