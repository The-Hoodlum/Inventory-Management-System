-- order_request.transfer permission.
--
-- Splits raising an inter-location TRANSFER (a stock manager decides source + destination,
-- possibly across branches) from raising a restock/sales request for one's own location
-- (order_request.create). Granted to stock-manager roles only — NOT Cashier — so a cashier
-- can requisition stock to their own location but cannot move stock between locations.

INSERT INTO permissions (code, description) VALUES
    ('order_request.transfer', 'Raise an inter-location stock transfer (source + destination)')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'order_request.transfer'
WHERE r.is_system AND r.name IN ('Admin', 'Warehouse Manager', 'Branch Manager')
ON CONFLICT DO NOTHING;
