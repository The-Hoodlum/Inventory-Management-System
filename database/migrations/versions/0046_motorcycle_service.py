"""motorcycle service follow-up — usage profile, per-model schedule, service log

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-11

Adds the pieces the service follow-up page needs: motorcycle_units.service_usage
(light/medium/heavy), motorcycle_service_plans (editable per-model schedule, with a
tenant default; module defaults when absent) and motorcycle_service_records (append-only
log of services performed). Additive + idempotent; no data changed. Reuses the existing
motorcycle permissions (no new permission seeded).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "motorcycle_service.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS motorcycle_service_records;")
    op.execute("DROP TABLE IF EXISTS motorcycle_service_plans;")
    op.execute("ALTER TABLE motorcycle_units DROP CONSTRAINT IF EXISTS motorcycle_units_service_usage_ck;")
    op.execute("ALTER TABLE motorcycle_units DROP COLUMN IF EXISTS service_usage;")
