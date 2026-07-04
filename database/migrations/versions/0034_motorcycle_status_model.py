"""motorcycle unit: five sale statuses + independent inspection/registration + hold reason

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-04

Splits the old folded lifecycle into independent facts:
  * ``status`` becomes ONE of five sale statuses (unassembled / assembled / reserved /
    on_hold / sold). Assembly is folded into it; inspection + registration are no longer
    statuses.
  * ``inspected`` (bool) replaces the ``inspection_status`` text column.
  * ``registered`` (bool) replaces the ``registration_status`` text column.
  * ``hold_reason`` (text) is new — populated while a unit is on hold.
  * ``assembly_status`` is dropped (folded into the sale status).

Existing units are migrated to the five statuses (mapping below). Additive columns +
value remap + drop of the three folded columns; no unit rows are deleted.

Old -> new sale status:
    received | assembly_required | in_assembly     -> unassembled
    assembled | inspected                           -> assembled
    reserved                                        -> reserved
    sold | delivered | registered | warranty_active -> sold
    cancelled                                       -> on_hold (customer cleared,
                                                       hold_reason set — on_hold carries none)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New independent-fact columns.
    op.execute("ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS inspected BOOLEAN NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS registered BOOLEAN NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS hold_reason TEXT;")

    # 2. Backfill the booleans from the old text columns — but ONLY when they still exist.
    # On a fresh DB the base table is already the new shape (0030 execs the updated
    # motorcycle_units.sql), so there is nothing to backfill and 0034 is a safe no-op.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'motorcycle_units' AND column_name = 'inspection_status') THEN
            UPDATE motorcycle_units SET inspected = (inspection_status = 'passed');
          END IF;
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'motorcycle_units' AND column_name = 'registration_status') THEN
            UPDATE motorcycle_units SET registered = (registration_status = 'registered');
          END IF;
        END $$;
        """
    )

    # 3. Cancelled units become on_hold; on_hold carries a reason and NO customer.
    op.execute(
        "UPDATE motorcycle_units "
        "SET hold_reason = 'Cancelled (migrated to on_hold)', customer_id = NULL "
        "WHERE status = 'cancelled';"
    )

    # 4. Remap OLD statuses to the five; PRESERVE any value that is already valid (so a
    # fresh new-shape table is untouched).
    op.execute(
        "UPDATE motorcycle_units SET status = CASE "
        "WHEN status IN ('received','assembly_required','in_assembly') THEN 'unassembled' "
        "WHEN status = 'inspected' THEN 'assembled' "
        "WHEN status IN ('delivered','registered','warranty_active') THEN 'sold' "
        "WHEN status = 'cancelled' THEN 'on_hold' "
        "ELSE status END;"
    )

    # 5. New default + drop the folded columns (no-ops on a fresh new-shape DB).
    op.execute("ALTER TABLE motorcycle_units ALTER COLUMN status SET DEFAULT 'unassembled';")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS inspection_status;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS assembly_status;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS registration_status;")


def downgrade() -> None:
    # Best-effort reverse: restore the folded columns from the booleans (lossy — the old
    # granular states cannot be recovered).
    op.execute("ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS inspection_status TEXT NOT NULL DEFAULT 'pending';")
    op.execute("ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS assembly_status TEXT NOT NULL DEFAULT 'not_required';")
    op.execute("ALTER TABLE motorcycle_units ADD COLUMN IF NOT EXISTS registration_status TEXT NOT NULL DEFAULT 'unregistered';")
    op.execute("UPDATE motorcycle_units SET inspection_status = CASE WHEN inspected THEN 'passed' ELSE 'pending' END;")
    op.execute("UPDATE motorcycle_units SET registration_status = CASE WHEN registered THEN 'registered' ELSE 'unregistered' END;")
    op.execute("ALTER TABLE motorcycle_units ALTER COLUMN status SET DEFAULT 'received';")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS hold_reason;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS registered;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS inspected;")
