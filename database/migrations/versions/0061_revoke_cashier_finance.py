"""Revoke the Cashier role's Finance access.

The Cashier was previously granted finance.read (view accounts/expenses/statements) and
finance.handover (record a till handover). Policy is now that front-line roles have NO
Finance access — only authorized roles (Admin, Finance, and Branch Manager for their
branch) may see or touch Finance. This removes both grants from Cashier for already-built
databases (mirrors the updated finance_expenses.sql + finance_transfers_handovers.sql).

Idempotent. Salesperson never held these, so nothing to do there.

Revision ID: 0061
Revises: 0060
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels = None
depends_on = None

_CASHIER_FINANCE = ("finance.read", "finance.handover")


def upgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions rp
        USING roles r, permissions p
        WHERE rp.role_id = r.id AND rp.permission_id = p.id
          AND r.is_system AND r.name = 'Cashier'
          AND p.code IN ('finance.read', 'finance.handover');
    """)


def downgrade() -> None:
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r JOIN permissions p
          ON p.code IN ('finance.read', 'finance.handover')
        WHERE r.is_system AND r.name = 'Cashier'
        ON CONFLICT DO NOTHING;
    """)
