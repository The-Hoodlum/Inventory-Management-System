"""generic data-import framework + inventory target

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-19

Adds the import framework tables (``import_jobs``, ``import_files``,
``import_errors``, ``import_mappings``), product-level ``unit_of_measure`` /
``currency`` / ``created_by_import_job_id``, the ``initial_import`` stock-movement
type, and the ``data.import`` permission — all via the idempotent DDL in
``sql/inventory_import.sql``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    ddl = (SQL_DIR / "inventory_import.sql").read_text(encoding="utf-8")
    op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS import_errors;")
    op.execute("DROP TABLE IF EXISTS import_files;")
    op.execute("DROP TABLE IF EXISTS import_mappings;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS created_by_import_job_id;")
    op.execute("DROP TABLE IF EXISTS import_jobs;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS unit_of_measure;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS currency;")
    op.execute(
        "ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_movement_type_check;"
    )
    op.execute(
        "ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_movement_type_check "
        "CHECK (movement_type IN "
        "('receipt','issue','adjustment','transfer_in','transfer_out',"
        "'damage','reserve','unreserve'));"
    )
    op.execute("DELETE FROM permissions WHERE code = 'data.import';")
