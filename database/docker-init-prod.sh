#!/usr/bin/env bash
# ============================================================================
#  Production database provisioning — runs ONCE, on the first boot of an empty
#  Postgres data volume (mounted into /docker-entrypoint-initdb.d).
#
#  Applies the full schema + RBAC + every feature module in dependency order, then
#  bootstraps ONE tenant + admin from env vars. Unlike the dev/eval path it seeds NO
#  demo business data. It creates and wipes nothing beyond the initial admin.
#
#  Ordering note: this is the single source of truth for the SQL-file order in a
#  demo-free install. When a feature adds a SQL file, append it to MODULES below.
#  (The `alembic upgrade head` path is the other supported bootstrap and must stay
#  equivalent — see docs/DEPLOYMENT.md.)
# ============================================================================
set -euo pipefail

SQL=/sql                 # mounted from ./database/sql
APPDOCKER=/appdocker     # mounted from ./backend/docker (app_user role)

run() { psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$@"; }

: "${ADMIN_EMAIL:?ADMIN_EMAIL must be set for the production bootstrap}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set for the production bootstrap}"

echo "[init] schema + app role + RBAC"
run -f "$SQL/schema.sql"
run -f "$APPDOCKER/02_app_role.sql"
run -f "$SQL/seed_rbac.sql"

# Feature modules, in dependency order (mirrors the eval stack MINUS the demo seeds:
# seed_demo, seed_demo_locations, seed_demo_branches, sample_motorcycle_demo).
MODULES=(
  po_events auth_hardening demand_source demand_forecasts intelligence reorder_risk
  product_profile supplier_scores inventory_import import_rollback product_profile_flags
  assistant assistant_roles tenant_settings tenant_branding order_requests
  order_request_completion import_targets_supplier_warehouse order_request_purposes
  order_request_transfers inventory_reservations branches stock_transfers
  stock_transfer_ledger customers sales_documents sales_returns motorcycle_units
  motorcycle_import dispatch_notes issuances customer_deliveries reconstruction
  product_wholesale_price user_branch_access order_request_transfer_permission
  bike_issues assembly_targets motorcycle_country_of_origin product_location motorcycle_service parts_sales vat
)
for m in "${MODULES[@]}"; do
  echo "[init] module: $m"
  run -f "$SQL/$m.sql"
done

echo "[init] bootstrap admin ($ADMIN_EMAIL)"
run -v admin_email="$ADMIN_EMAIL" \
    -v admin_password="$ADMIN_PASSWORD" \
    -v tenant_name="${TENANT_NAME:-My Company}" \
    -v tenant_slug="${TENANT_SLUG:-main}" \
    -f "$SQL/seed_admin.sql"

echo "[init] production provisioning complete."
