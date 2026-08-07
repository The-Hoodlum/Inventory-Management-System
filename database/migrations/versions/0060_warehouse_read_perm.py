"""Add the 'warehouse.read' permission (read-only view of branches + warehouses) and grant
it to the oversight/management roles.

The Branches and Warehouses pages used to be gated on 'inventory.read', which front-line
roles (Cashier) also hold for POS stock lookups — so they could see those admin pages.
This adds a dedicated read permission so viewing branch/warehouse structure can be granted
to oversight roles (Admin, Inventory/Warehouse/Procurement Manager, Branch Manager, Viewer,
Mechanic) without exposing it to Cashier / Salesperson. Writes remain 'warehouse.manage'.

Idempotent — mirrors seed_rbac.sql + assistant_roles.sql for already-built databases.

Revision ID: 0060
Revises: 0059
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels = None
depends_on = None

_ROLES = (
    "Admin",
    "Inventory Manager",
    "Warehouse Manager",
    "Procurement Manager",
    "Branch Manager",
    "Viewer",
    "Mechanic",
)


def upgrade() -> None:
    op.execute("""
        INSERT INTO permissions (code, description)
        VALUES ('warehouse.read', 'View branches and warehouses (read-only)')
        ON CONFLICT (code) DO NOTHING;
    """)
    values = ", ".join(f"('{name}')" for name in _ROLES)
    op.execute(f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code = 'warehouse.read'
        JOIN (VALUES {values}) AS want(name) ON want.name = r.name
        WHERE r.is_system
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions rp
        USING permissions p
        WHERE rp.permission_id = p.id AND p.code = 'warehouse.read';
    """)
    op.execute("DELETE FROM permissions WHERE code = 'warehouse.read';")
