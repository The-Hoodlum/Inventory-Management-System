# Database Layer — Inventory Management & Procurement Platform

Phase 1 (MVP) database layer: **schema, migrations, and ERD only**. No backend or frontend application code is included — that is the next slice. Everything here is PostgreSQL 16+.

## Contents

```
database/
├── README.md                     # this file
├── ERD.md                        # entity-relationship diagram (Mermaid)
├── alembic.ini                   # Alembic config (DB URL via $DATABASE_URL)
├── sql/
│   ├── schema.sql                # canonical DDL — single source of truth
│   ├── seed_rbac.sql             # permissions + 5 system roles (required)
│   └── seed_demo.sql             # optional generic demo data (dev only)
└── migrations/
    ├── env.py                    # Alembic runner (no app imports)
    ├── script.py.mako            # revision template
    └── versions/
        ├── 0001_initial_schema.py   # executes sql/schema.sql
        └── 0002_seed_rbac.py        # executes sql/seed_rbac.sql
```

## Prerequisites

- PostgreSQL **16+**
- For the Alembic path: Python 3.11+, `pip install alembic psycopg2-binary`
- The initial migration creates extensions (`pgcrypto`, `pg_trgm`, `citext`), so it must run as a role allowed to `CREATE EXTENSION` (a superuser, or `rds_superuser`/cloud equivalent).

## Setup

You can apply the schema two ways. **Use one or the other, not both.**

### Option A — Alembic (recommended for ongoing development)

```bash
createdb inventory
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/inventory"

cd database
alembic upgrade head          # runs 0001 (schema) then 0002 (RBAC seed)

# optional demo data:
psql "postgresql://postgres:postgres@localhost:5432/inventory" -f sql/seed_demo.sql
```

To preview the SQL without touching a database: `alembic upgrade head --sql`.
To roll back everything: `alembic downgrade base`.

### Option B — Plain psql (quickest one-off)

```bash
createdb inventory
export PG="postgresql://postgres:postgres@localhost:5432/inventory"

psql "$PG" -f sql/schema.sql
psql "$PG" -f sql/seed_rbac.sql
psql "$PG" -f sql/seed_demo.sql      # optional
```

After loading the demo, log in (once the backend exists) with **`admin@demo.com` / `ChangeMe123!`** — the demo's password hash is a real bcrypt hash generated in-database via `pgcrypto`.

## Application database role & Row-Level Security (important)

Tenant data is isolated by **PostgreSQL Row-Level Security** on the business tables, with `FORCE ROW LEVEL SECURITY` so even the table owner is subject to the policy. Two things make this work:

1. The application connects as a **dedicated non-superuser role** (superusers bypass RLS).
2. On every request, the app sets the current tenant for the connection:
   ```sql
   SET app.current_tenant = '<tenant-uuid>';   -- per request / per transaction
   ```
   The RLS policy then restricts every query to `tenant_id = current_setting('app.current_tenant')`.

Create and grant the application role (run once, as a superuser):

```sql
CREATE ROLE app_user LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE inventory TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_user;
-- apply automatically to future objects too:
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO app_user;
```

> Migrations run as the privileged/owner role; the running app uses `app_user`. The seed scripts call `set_config('app.current_tenant', ...)` themselves, so they work under either role.

### RLS scope — a deliberate decision

RLS is applied to the **business-data** tables: `categories, brands, suppliers, products, supplier_products, warehouses, inventory, stock_movements, sales_daily, purchase_orders, purchase_order_lines, reorder_recommendations, audit_logs, po_counters`.

The **identity/RBAC** tables (`users, roles, permissions, role_permissions, user_roles`) are intentionally **not** under RLS. Login must look up a user by email *before* a tenant context exists, which would deadlock against a tenant policy. Isolation for users is instead enforced by the `(tenant_id, email)` unique key plus tenant filtering in the application/repository layer. If you later adopt subdomain-per-tenant login, users can be moved under RLS with no schema change.

## Design decisions baked into this schema

1. **Money & quantities are `NUMERIC(18,4)`** (FX rates `NUMERIC(18,6)`) — never floating point.
2. **Append-only ledger** (`stock_movements`) is the source of truth for stock history; `inventory` is the transactionally-maintained running balance, with `qty_available` as a **generated column** that cannot drift.
3. **Multi-tenant via shared schema + `tenant_id` + RLS** — cheap to operate, upgradeable to stronger isolation later.
4. **Soft deletes** on `products` and `suppliers` (`deleted_at`) with **partial unique indexes** (`WHERE deleted_at IS NULL`) so a retired SKU/name can be reused without breaking historical POs and movements.
5. **Multi-sourcing first-class** — `supplier_products` holds per-supplier cost/MOQ/lead-time/pack-size; `products` holds defaults.
6. **Pallet & container fields stored, unused** (`weight_per_unit/carton`, `volume_per_unit/carton`, `cartons_per_pallet`) — ready for Phase 3 container optimization, per Inventory Rules #3/#4.
7. **PO numbering** via a concurrency-safe `next_po_number(tenant)` function backed by `po_counters` → `PO-YYYY-00001`.
8. **Optimistic locking** via `version` columns on `inventory` and `purchase_orders` (app does compare-and-swap).
9. **`updated_at` maintained by trigger** (`set_updated_at`) on mutable tables.
10. **Status fields constrained by `CHECK`** rather than enum types — easier to extend via migration.

## Data dictionary (summary)

| Table | Purpose |
|---|---|
| `tenants` | Customer organizations; base currency, FX rate, VAT rate |
| `users` | Login accounts, scoped to a tenant |
| `roles` / `permissions` / `role_permissions` / `user_roles` | RBAC: roles bundle permissions; users get roles |
| `audit_logs` | Immutable before/after (JSONB) record of every state change |
| `categories` / `brands` | Product classification (categories are hierarchical) |
| `suppliers` | Vendor master: terms, currency, default lead time |
| `products` | Item master: SKU, prices, pack size, MOQ, lead time, reorder params, pallet/container dims |
| `supplier_products` | Per-supplier price/MOQ/lead-time/pack-size (multi-sourcing) |
| `warehouses` | Stocking locations / branches |
| `inventory` | On-hand / reserved / damaged + generated available, per (product, warehouse) |
| `stock_movements` | Append-only ledger of all stock changes |
| `sales_daily` | Daily units sold per product/warehouse — feeds the reorder engine |
| `purchase_orders` / `purchase_order_lines` | Procurement orders and their line items |
| `po_counters` | Backing store for `next_po_number()` |
| `reorder_recommendations` | Output of the reorder engine awaiting review/conversion to POs |

## Migration discipline

- **Never edit a migration that has been applied** to a shared/production database. Make a new revision.
- Generate the next revision with `alembic revision -m "add X"` (autogenerate stays off until ORM models land — `target_metadata` is `None` in `env.py`).
- The canonical DDL lives in `sql/schema.sql`; migration `0001` executes it, so there is exactly one place to read the current full schema.

## What is intentionally NOT here yet

No SQLAlchemy ORM models, FastAPI services/endpoints, auth, or React UI — those belong to the next build slices (backend core and the reorder engine). This package is purely the database foundation they will sit on.
