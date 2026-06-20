-- ============================================================================
--  Application database role (LOCAL DEV / COMPOSE ONLY)
--
--  Runs as the postgres superuser via docker-entrypoint-initdb.d, AFTER
--  01_schema.sql has created the tables. The application connects as this
--  NON-superuser role so that PostgreSQL Row-Level Security is enforced
--  (superusers bypass RLS).
--
--  Change the password for any non-local environment and manage it as a secret.
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user LOGIN PASSWORD 'app_pw';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE inventory TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_user;

-- Apply automatically to objects created later, too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO app_user;
