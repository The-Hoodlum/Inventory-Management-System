# Backend — Inventory Management & Procurement Platform

FastAPI service implementing authentication, RBAC, and the Product, Supplier,
Warehouse, and Inventory modules on top of the PostgreSQL schema in the sibling
`database/` package. Async throughout (SQLAlchemy 2.0 + asyncpg).

## Architecture

```
HTTP  ──▶  API layer (FastAPI routers, deps)        app/api/v1
            │   auth (JWT) · RBAC guard · request transaction · sets tenant GUC
            ▼
        Service layer (business rules, audit)        app/services
            │   no SQL specifics; injected repositories; unit-testable
            ▼
        Repository layer (data access)               app/repositories
            │   async SQLAlchemy queries, row locking, ledger writes
            ▼
        Models  (ORM mapped to existing schema)       app/models
            ▼
        PostgreSQL  (RLS-enforced, see database/)
```

Layout:

```
backend/
├── app/
│   ├── main.py                 # app factory: CORS, routers, handlers, /health
│   ├── core/                   # config, security (JWT/bcrypt), exceptions, permissions, logging
│   ├── db/                     # declarative base, async engine/session
│   ├── models/                 # ORM models mapped onto the database schema
│   ├── schemas/                # Pydantic request/response models
│   ├── repositories/           # data-access layer
│   ├── services/               # business logic + auditing
│   └── api/v1/                 # deps, router, endpoints/{auth,products,suppliers,warehouses,inventory}
├── tests/                      # unit tests (fakes; no DB needed)
├── docker/                     # entrypoint + app-role bootstrap SQL
├── Dockerfile · docker-compose.yml · requirements*.txt · pyproject.toml · .env.example
```

## Quick start (Docker Compose)

From the **repository root** (so `../database` resolves):

```bash
cd backend
docker compose up --build
```

Compose starts PostgreSQL, bootstraps it from `../database/sql` (schema → app role
→ RBAC seed → demo seed), and runs the API as the non-superuser `app_user` so RLS
is enforced. Then:

- API:      http://localhost:8000
- Docs:     http://localhost:8000/docs
- Health:   http://localhost:8000/health

Demo login (from the database demo seed): **`admin@demo.com` / `ChangeMe123!`**

## Quick start (local Python)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # then edit JWT_SECRET_KEY and DATABASE_URL

# Provision the database first (see ../database): apply schema + seed_rbac (+ optional seed_demo)
# and create the app_user role (docker/02_app_role.sql) if connecting as a non-superuser.

uvicorn app.main:app --reload
```

> **Important:** `DATABASE_URL` must use the async driver
> (`postgresql+asyncpg://…`) and the app must connect as a **non-superuser** role
> for Row-Level Security to take effect (superusers bypass RLS).

## Authentication & authorization

- `POST /api/v1/auth/login` → `{access_token, refresh_token, token_type, expires_in}`.
  Body: `{email, password, tenant_slug?}` (slug only needed if the same email
  exists across multiple tenants).
- `POST /api/v1/auth/refresh` → new token pair from a valid refresh token.
- `GET  /api/v1/auth/me` → current user, roles, and permissions.
- Send the access token as `Authorization: Bearer <token>` on all other calls.
- Each endpoint enforces a permission (e.g. `product.create`, `inventory.transfer`)
  from the RBAC seed; missing permission → `403`.

## Endpoints

| Method | Path | Permission |
|---|---|---|
| POST | `/api/v1/auth/login` | — |
| POST | `/api/v1/auth/refresh` | — |
| GET | `/api/v1/auth/me` | authenticated |
| POST | `/api/v1/products` | `product.create` |
| GET | `/api/v1/products` | `product.read` |
| GET | `/api/v1/products/{id}` | `product.read` |
| PATCH | `/api/v1/products/{id}` | `product.update` |
| DELETE | `/api/v1/products/{id}` | `product.delete` (soft delete) |
| POST | `/api/v1/suppliers` | `supplier.create` |
| GET | `/api/v1/suppliers` | `supplier.read` |
| GET | `/api/v1/suppliers/{id}` | `supplier.read` |
| PATCH | `/api/v1/suppliers/{id}` | `supplier.update` |
| DELETE | `/api/v1/suppliers/{id}` | `supplier.update` (soft delete) |
| POST | `/api/v1/warehouses` | `warehouse.manage` |
| GET | `/api/v1/warehouses` | `inventory.read` |
| GET | `/api/v1/warehouses/{id}` | `inventory.read` |
| PATCH | `/api/v1/warehouses/{id}` | `warehouse.manage` |
| DELETE | `/api/v1/warehouses/{id}` | `warehouse.manage` (409 if it has history) |
| POST | `/api/v1/inventory/receive` | `inventory.receive` |
| POST | `/api/v1/inventory/issue` | `inventory.issue` |
| POST | `/api/v1/inventory/adjust` | `inventory.adjust` |
| POST | `/api/v1/inventory/transfer` | `inventory.transfer` |
| GET | `/api/v1/inventory` | `inventory.read` |
| GET | `/api/v1/inventory/movements` | `inventory.read` |

Product search: `GET /api/v1/products?search=<text>&category_id=&brand_id=&supplier_id=&status=&page=&page_size=`.

## Inventory semantics

- Stock lives in `inventory` as a running balance per `(product, warehouse)`;
  `qty_available` is a DB-generated column (`on_hand − reserved − damaged`).
- Every receive / issue / adjust / transfer:
  1. locks the affected inventory row(s) (`SELECT … FOR UPDATE`; transfers lock in
     a deterministic order to avoid deadlocks),
  2. updates the balance and bumps the optimistic-lock `version`,
  3. appends to the **`stock_movements`** ledger (signed quantity; transfers write
     a `transfer_out` and a `transfer_in`),
  4. writes an **`audit_logs`** entry — **every movement is audited**.
- Issues and transfers fail with `400` if available stock is insufficient;
  adjustments fail if they would drive on-hand below zero.
- All of the above happens inside a single request transaction, so a failure
  rolls back the balance, the ledger row(s), and the audit entry together.

## Error format

```json
{ "error": { "code": "conflict", "message": "…", "details": [ … ] } }
```

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

The unit tests use in-memory fakes (no database) and cover password/JWT handling,
the RBAC check, product CRUD rules, and the full inventory engine (receive,
insufficient-stock guards, adjust bounds, transfer atomicity, and auditing).

## Configuration

All settings come from environment variables / `.env` (see `.env.example`):
`DATABASE_URL`, `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`REFRESH_TOKEN_EXPIRE_DAYS`, `CORS_ORIGINS`, `LOG_LEVEL`, and more.

## Not in this slice

Purchase orders, the reorder engine, reporting/exports, and user-management
endpoints are intentionally out of scope here (next build slices). The schema and
permissions already accommodate them.
