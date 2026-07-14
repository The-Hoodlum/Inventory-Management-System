"""Support selling motorcycles before they are assembled.

Adds ``motorcycle_units.assembly_pending`` — TRUE when a unit was SOLD before assembly and
the dealership still owes assembly before it can be delivered (a reseller sale, where the
buyer assembles it themselves, leaves this FALSE). Also backfills ``assembled_date`` for
units that are (or were sold while) assembled so "is it assembled?" is reliable going
forward — the old rule only allowed selling from ``assembled``/``reserved``.

Revision ID: 0052
Revises: 0051
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "motorcycle_units",
        sa.Column("assembly_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("""
        UPDATE motorcycle_units
        SET assembled_date = COALESCE(assembled_date, date_received, created_at::date)
        WHERE status IN ('assembled', 'reserved', 'sold') AND assembled_date IS NULL;
    """)


def downgrade() -> None:
    op.drop_column("motorcycle_units", "assembly_pending")
