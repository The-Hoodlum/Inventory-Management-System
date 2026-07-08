-- ============================================================================
--  Production first-admin bootstrap — create ONE tenant + ONE Admin user.
--
--  This is the production counterpart to seed_demo.sql: it seeds NO demo business
--  data, only the initial company (tenant) and its administrator so you can log in.
--  Idempotent — safe to run more than once; it never overwrites an existing admin
--  or tenant, and it wipes nothing.
--
--  Driven by psql variables (passed by docker-init-prod.sh from environment):
--    :admin_email     the administrator's login email
--    :admin_password  their initial password (bcrypt-hashed here via pgcrypto)
--    :tenant_name     the company name shown in the app
--    :tenant_slug     a short url-safe identifier, unique per install
--
--  SECURITY: the password is hashed with bcrypt (pgcrypto crypt/gen_salt) exactly as
--  the app expects — the plaintext is never stored. Change it after first login.
-- ============================================================================

-- 1) Tenant (no RLS on tenants). Created only if the slug is new.
INSERT INTO tenants (name, slug, base_currency, fx_rate, vat_rate)
SELECT :'tenant_name', :'tenant_slug', 'USD', 1.000000, 0.0000
WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE slug = :'tenant_slug');

-- 2) Scope the session to that tenant so the RLS WITH CHECK on users passes.
SELECT set_config('app.current_tenant',
                  (SELECT id::text FROM tenants WHERE slug = :'tenant_slug'), false);

-- 3) Admin user with a real, verifiable bcrypt hash. Created only if absent.
INSERT INTO users (tenant_id, email, password_hash, full_name)
SELECT t.id, :'admin_email', crypt(:'admin_password', gen_salt('bf', 12)), 'Administrator'
FROM tenants t
WHERE t.slug = :'tenant_slug'
  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.email = :'admin_email');

-- 4) Grant the global Admin system role (seeded by seed_rbac.sql / migration 0002).
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id
FROM users u
JOIN roles r ON r.is_system AND r.name = 'Admin'
WHERE u.email = :'admin_email'
ON CONFLICT DO NOTHING;

-- 5) Confirm the admin exists and carries the Admin role (prints during init).
SELECT u.email AS admin_email, t.slug AS tenant, r.name AS role
FROM users u
JOIN tenants t ON t.id = u.tenant_id
JOIN user_roles ur ON ur.user_id = u.id
JOIN roles r ON r.id = ur.role_id
WHERE u.email = :'admin_email' AND r.is_system AND r.name = 'Admin';
