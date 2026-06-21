-- ============================================================================
--  Assistant front-line roles (idempotent; safe to re-run).
--
--  Adds three system roles used by the conversational assistant's role-based tool
--  access, and grants each a sensible read set plus `assistant.use`:
--    * Branch Manager — runs a single branch (branch scope via user_warehouse_access);
--                       full assistant tool access.
--    * Cashier        — stock lookups + sales reports only.
--    * Mechanic       — parts lookups + service info only.
--
--  The assistant ENFORCES the per-tool limits in code (app/assistant/domain/
--  capabilities.py); these grants just let the roles sign in and use the read APIs.
--  Run after seed_rbac.sql.
-- ============================================================================

INSERT INTO roles (tenant_id, name, description, is_system) VALUES
    (NULL, 'Branch Manager', 'Runs a single branch (scoped via warehouse access); full assistant', TRUE),
    (NULL, 'Cashier',        'Front desk: stock lookups and sales reports',                         TRUE),
    (NULL, 'Mechanic',       'Workshop: parts lookups and service information',                     TRUE)
ON CONFLICT DO NOTHING;

-- Branch Manager: branch-wide read access + assistant (branch scope via warehouse grants).
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read', 'supplier.read', 'inventory.read',
    'reorder.read', 'po.read', 'report.read', 'dashboard.read', 'assistant.use'
)
WHERE r.is_system AND r.name = 'Branch Manager'
ON CONFLICT DO NOTHING;

-- Cashier: stock + sales reads + assistant.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read', 'inventory.read', 'report.read', 'dashboard.read', 'assistant.use'
)
WHERE r.is_system AND r.name = 'Cashier'
ON CONFLICT DO NOTHING;

-- Mechanic: parts (catalog + stock) reads + assistant.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read', 'inventory.read', 'assistant.use'
)
WHERE r.is_system AND r.name = 'Mechanic'
ON CONFLICT DO NOTHING;
