"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-09

Creates the full database schema by executing the canonical DDL in
``sql/schema.sql`` (the single source of truth). Keeping the DDL in one place
avoids drift between the migration and a hand-maintained schema file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# repo root = migrations/versions/ -> migrations/ -> <root>/
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    schema_sql = (SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    # psycopg2 executes multiple ';'-separated statements (and dollar-quoted
    # function/DO bodies) correctly in a single call.
    op.execute(schema_sql)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reorder_recommendations CASCADE;
        DROP TABLE IF EXISTS purchase_order_lines    CASCADE;
        DROP TABLE IF EXISTS purchase_orders         CASCADE;
        DROP TABLE IF EXISTS po_counters             CASCADE;
        DROP TABLE IF EXISTS sales_daily             CASCADE;
        DROP TABLE IF EXISTS stock_movements         CASCADE;
        DROP TABLE IF EXISTS inventory               CASCADE;
        DROP TABLE IF EXISTS warehouses              CASCADE;
        DROP TABLE IF EXISTS supplier_products       CASCADE;
        DROP TABLE IF EXISTS products                CASCADE;
        DROP TABLE IF EXISTS suppliers               CASCADE;
        DROP TABLE IF EXISTS brands                  CASCADE;
        DROP TABLE IF EXISTS categories              CASCADE;
        DROP TABLE IF EXISTS audit_logs              CASCADE;
        DROP TABLE IF EXISTS user_roles              CASCADE;
        DROP TABLE IF EXISTS role_permissions        CASCADE;
        DROP TABLE IF EXISTS permissions             CASCADE;
        DROP TABLE IF EXISTS roles                   CASCADE;
        DROP TABLE IF EXISTS users                   CASCADE;
        DROP TABLE IF EXISTS tenants                 CASCADE;

        DROP FUNCTION IF EXISTS next_po_number(uuid);
        DROP FUNCTION IF EXISTS set_updated_at();
        -- Extensions (pgcrypto, pg_trgm, citext) are left in place; they are
        -- shared and harmless to retain.
        """
    )
