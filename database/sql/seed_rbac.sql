-- ============================================================================
--  RBAC REFERENCE DATA  (system bootstrap — required for the app to function)
--
--  Idempotent: safe to run repeatedly. Inserts the global permission catalog,
--  the five built-in system roles, and their permission mappings.
--
--  Run after schema.sql:   psql "$DATABASE_URL" -f sql/seed_rbac.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Permissions catalog
-- ----------------------------------------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('product.read',       'View products'),
    ('product.create',     'Create products'),
    ('product.update',     'Edit products'),
    ('product.delete',     'Delete (soft) products'),
    ('supplier.read',      'View suppliers'),
    ('supplier.create',    'Create suppliers'),
    ('supplier.update',    'Edit suppliers'),
    ('warehouse.manage',   'Create / edit warehouses'),
    ('inventory.read',     'View inventory and movements'),
    ('inventory.receive',  'Receive stock (incl. PO receiving)'),
    ('inventory.issue',    'Issue / consume stock'),
    ('inventory.adjust',   'Adjust counts and mark damage'),
    ('inventory.transfer', 'Transfer stock between warehouses'),
    ('reorder.read',       'View reorder recommendations'),
    ('reorder.run',        'Trigger reorder recalculation'),
    ('reorder.manage',     'Accept / dismiss recommendations'),
    ('po.read',            'View purchase orders'),
    ('po.create',          'Create / edit / submit purchase orders'),
    ('po.update',          'Edit draft purchase orders'),
    ('po.approve',         'Approve / reject purchase orders'),
    ('report.read',        'View reports'),
    ('report.export',      'Export reports (CSV / XLSX)'),
    ('user.manage',        'Manage users and role assignments'),
    ('settings.manage',    'Manage tenant settings (FX, VAT, etc.)'),
    ('dashboard.read',     'View the dashboard'),
    ('data.import',        'Import data from spreadsheets (products, inventory, ...)'),
    ('assistant.use',      'Use the natural-language assistant (WhatsApp / API)')
ON CONFLICT (code) DO NOTHING;

-- ----------------------------------------------------------------------------
-- System roles (global: tenant_id IS NULL, is_system = TRUE)
-- ----------------------------------------------------------------------------
INSERT INTO roles (tenant_id, name, description, is_system) VALUES
    (NULL, 'Admin',              'Full access to all features and settings',          TRUE),
    (NULL, 'Inventory Manager',  'Manages catalog, stock, and reorder planning',      TRUE),
    (NULL, 'Procurement Manager','Manages suppliers and purchase orders',             TRUE),
    (NULL, 'Warehouse Manager',  'Full branch operations: catalog, stock, purchase orders, reordering', TRUE),
    (NULL, 'Viewer',             'Read-only access',                                  TRUE)
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- Mappings
-- ----------------------------------------------------------------------------
-- Admin → every permission
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r CROSS JOIN permissions p
WHERE r.is_system AND r.name = 'Admin'
ON CONFLICT DO NOTHING;

-- Inventory Manager
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read','product.create','product.update','product.delete',
    'supplier.read','warehouse.manage',
    'inventory.read','inventory.receive','inventory.issue','inventory.adjust','inventory.transfer',
    'reorder.read','reorder.run','reorder.manage',
    'po.read','report.read','report.export','dashboard.read','data.import'
)
WHERE r.is_system AND r.name = 'Inventory Manager'
ON CONFLICT DO NOTHING;

-- Procurement Manager
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read',
    'supplier.read','supplier.create','supplier.update',
    'inventory.read',
    'reorder.read','reorder.run','reorder.manage',
    'po.read','po.create','po.update','po.approve',
    'report.read','report.export','dashboard.read'
)
WHERE r.is_system AND r.name = 'Procurement Manager'
ON CONFLICT DO NOTHING;

-- Warehouse Manager
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read','product.create','product.update',
    'supplier.read','supplier.create','supplier.update',
    'warehouse.manage',
    'inventory.read','inventory.receive','inventory.issue','inventory.adjust','inventory.transfer',
    'reorder.read','reorder.run','reorder.manage',
    'po.read','po.create','po.update','po.approve',
    'report.read','dashboard.read','data.import'
)
WHERE r.is_system AND r.name = 'Warehouse Manager'
ON CONFLICT DO NOTHING;

-- Viewer
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r JOIN permissions p ON p.code IN (
    'product.read','supplier.read','inventory.read','reorder.read','po.read','report.read','dashboard.read'
)
WHERE r.is_system AND r.name = 'Viewer'
ON CONFLICT DO NOTHING;
