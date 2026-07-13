"""Grant the Cashier + Salesperson roles the quote/invoice permissions so front-desk staff
can create quotations and invoices for a customer (bikes by chassis / parts by SKU).

Cashier gains sales.quote + sales.invoice; Salesperson gains sales.invoice (it already had
quote + order). Idempotent — mirrors the updated customers.sql for already-built databases.

Revision ID: 0051
Revises: 0050
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r JOIN permissions p
          ON p.code IN ('sales.quote', 'sales.invoice')
        WHERE r.is_system AND r.name = 'Cashier'
        ON CONFLICT DO NOTHING;
    """)
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'sales.invoice'
        WHERE r.is_system AND r.name = 'Salesperson'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions rp USING roles r, permissions p
        WHERE rp.role_id = r.id AND rp.permission_id = p.id
          AND r.is_system AND r.name = 'Cashier'
          AND p.code IN ('sales.quote', 'sales.invoice');
    """)
    op.execute("""
        DELETE FROM role_permissions rp USING roles r, permissions p
        WHERE rp.role_id = r.id AND rp.permission_id = p.id
          AND r.is_system AND r.name = 'Salesperson' AND p.code = 'sales.invoice';
    """)
