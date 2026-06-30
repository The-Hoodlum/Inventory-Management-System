"""supplier & warehouse import columns

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-24

Adds suppliers.code / suppliers.address and warehouses.branch / warehouses.warehouse_type
to back the new Supplier and Warehouse spreadsheet-import targets, via the idempotent
DDL in sql/import_targets_supplier_warehouse.sql.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "import_targets_supplier_warehouse.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS warehouse_type;")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS branch;")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS address;")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS code;")
