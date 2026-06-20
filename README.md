# Inventory & Procurement Platform

A multi-tenant Inventory Management & Procurement SaaS.

- **Backend:** Python / FastAPI · PostgreSQL (async SQLAlchemy 2.0) · JWT auth · row-level-security tenant isolation
- **Frontend:** React 18 + Vite + TypeScript + Tailwind + TanStack Query
- **Covers:** catalog, inventory (receive/issue/adjust/transfer + ledger), reorder engine, full purchase-order lifecycle (with PDF + email), reports, dashboards, user administration, and auth/edge hardening.

---

## Project structure

```
.
├── docker-compose.yml      # runs Postgres + the API (this file)
├── .env.example            # optional overrides for compose
├── README.md
├── TESTING_GUIDE.md        # detailed, step-by-step test walkthrough
├── backend/                # FastAPI app, Dockerfile, tests
├── frontend/               # React app (run with npm)
└── database/               # SQL schema, seeds, migrations
```

---

## Prerequisites

- **Docker Desktop** (running) — for the database + API
- **Node.js 18+** and **npm** — for the frontend

---

## Quick start

Open the folder in VS Code, then use **two terminals**.

### 1) Backend + database (Docker) — from the project root
```bash
docker compose down -v        # clean slate (skip on the very first run)
docker compose up --build
```
Verify:
- Health: http://localhost:8000/health → `{"status":"ok",...}`
- API docs (Swagger): http://localhost:8000/docs

### 2) Frontend (npm) — in a second terminal
```bash
cd frontend
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
npm install
npm run build                 # recommended first: type-checks everything
npm run dev
```
Open http://localhost:5173

### Log in
- **Email:** `admin@demo.com`
- **Password:** `ChangeMe123!`

Demo data (a tenant with warehouses, suppliers, products, starting stock, and
~90 days of sales) is **seeded automatically** on first boot.

---

## Common commands

| Action | Command |
|---|---|
| Start (build if needed) | `docker compose up --build` |
| Stop, keep data | `docker compose down` |
| Reset (wipe DB + re-seed) | `docker compose down -v` |
| Backend logs | `docker compose logs api --tail=80` |
| Frontend dev server | `cd frontend && npm run dev` |

---

## Notes

- **Stale database:** Postgres only seeds on a *first* boot. If login fails after
  an earlier run, do `docker compose down -v` then `up --build`.
- **Frontend build:** `npm run build` runs the strict TypeScript compiler. Run it
  before `npm run dev`; it's the quickest way to surface any type issue.
- **Production:** set a strong `JWT_SECRET_KEY` (the app refuses to boot in
  `production` with the default), lock `CORS_ORIGINS` to your domain, terminate
  TLS at a proxy, and back the rate limiter with Redis for multi-instance.
- **Full walkthrough:** see **TESTING_GUIDE.md** for a detailed, click-by-click
  test of the entire workflow (product → purchase-order receiving), API testing,
  and troubleshooting.

## Configuration

All compose settings have working defaults; override them via a root `.env`
(see `.env.example`). The frontend reads `frontend/.env` (`VITE_API_BASE_URL`).
