"""tenant business-identity settings (industry-agnostic SaaS)

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-21

Adds brand_name, industry, country, timezone, logo_url, assistant_name,
assistant_prompt, and feature_flags to tenants via the idempotent DDL in
``sql/tenant_settings.sql``. Company name reuses ``name``; default currency reuses
``base_currency``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "tenant_settings.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for col in ("brand_name", "industry", "country", "timezone", "logo_url",
                "assistant_name", "assistant_prompt", "feature_flags"):
        op.execute(f"ALTER TABLE tenants DROP COLUMN IF EXISTS {col};")
