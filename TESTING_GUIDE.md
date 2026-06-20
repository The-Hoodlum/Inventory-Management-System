# Inventory & Procurement Platform — Local Testing Guide

A complete, copy‑paste walkthrough to run the app on your machine and test the
whole workflow from **product creation → purchase‑order receiving**, plus
optional API testing, automated tests, and troubleshooting.

> **Time:** ~20–40 min (most of it is the one‑time Docker image build + `npm install`).
> **You'll use two terminals:** one for the backend (Docker), one for the frontend (npm).
> **Demo login:** `admin@demo.com` / `ChangeMe123!`

---

## 0. What you need (and how to check)

| Tool | Why | Check it's installed |
|---|---|---|
| **Docker Desktop** | runs Postgres + the API | `docker --version` and `docker compose version` |
| **Node.js 18+** | runs the React frontend | `node -v` (want v18, v20, or v22) and `npm -v` |

If a command says "not found":
- **Docker Desktop:** install from docker.com, launch it, and wait until the whale icon says *Running*.
- **Node.js:** install the LTS from nodejs.org (or via `nvm`).

> **Windows users:** run the commands below in **PowerShell**. Where I write
> `cp` (copy), use `Copy-Item` instead (noted again where it matters). Docker
> commands are identical.

---

## 1. Get the project

Unzip `inventory-procurement-platform.zip`. You should have:

```
inventory-procurement-platform/
├── backend/      ← FastAPI app + docker-compose.yml
├── database/     ← SQL schema + seed data
├── frontend/     ← React app
└── README.md
```

Open a terminal at the `inventory-procurement-platform` folder.

---

## 2. Part A — Start the backend + database (Terminal 1)

```bash
cd backend
docker compose down -v        # ensures a clean database (safe to run anytime)
docker compose up --build
```

- `down -v` deletes any old database volume so the schema + demo data are
  re‑created fresh. **Always run it if you've started this project before** —
  Postgres only seeds on a *first* boot, so a stale volume is the #1 cause of
  "login doesn't work."
- `up --build` builds the API image and starts both containers. The **first**
  build downloads Python packages and can take a few minutes.

### What success looks like
You'll see Postgres start, then run the init scripts (`01_schema` … `06_auth_hardening`), then the API log lines, ending with something like:

```
api-1  | INFO ... app_started ... env=development
api-1  | INFO:     Uvicorn running on http://0.0.0.0:8000
```

Leave this terminal running.

### Verify the backend is up
Open these in a browser:
- **Health:** http://localhost:8000/health → `{"status":"ok","environment":"development"}`
- **API docs (Swagger):** http://localhost:8000/docs → interactive list of every endpoint

✅ **Proves:** the database provisioned, the app booted, and RLS/auth wiring loaded.

---

## 3. Part B — Start the frontend (Terminal 2)

Open a **second** terminal at the project root.

```bash
cd frontend
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
npm install                   # one-time; downloads dependencies
npm run build                 # RECOMMENDED first: this type-checks everything
npm run dev
```

- `.env` sets `VITE_API_BASE_URL=http://localhost:8000/api/v1` (matches the backend).
- **`npm run build` is the most important early check.** It runs the strict
  TypeScript compiler. If it prints errors, **stop and send me the full output** —
  that's the one thing I couldn't verify in my environment, and it's quick to fix.
  If it succeeds, `npm run dev` will definitely serve.
- `npm run dev` starts Vite and prints a local URL.

### Open the app
Go to **http://localhost:5173** → you should see the **login page**.

---

## 4. Part C — Log in

Enter:
- **Email:** `admin@demo.com`
- **Password:** `ChangeMe123!`

You should land on the **Dashboard** with KPI cards (inventory value, health
score, open POs, low/out‑of‑stock counts) and a purchase‑order status chart.

**Sidebar (left):** Dashboard · Reports · Purchase Orders · Reorder · Inventory ·
Stock Movements · Products · Suppliers · Warehouses · Users.

✅ **Proves:** login → JWT issued → `/auth/me` loaded → permissions drive the nav → dashboard query + tenant isolation all work.

---

## 5. Part D — Full workflow test (product → PO receiving)

Do these **in order**. Each step lists the screen, the action, and what you should
see. The demo tenant already has suppliers/warehouses/products, but we'll create
fresh ones so you exercise the create paths too.

### D1 — Create a Supplier
**Suppliers → New supplier.** Fill in:
- Name: `Test Supplier Co`
- Currency: `USD`
- Default lead time (days): `7`
- (contact/email/phone optional) → **Save**

✅ It appears in the suppliers list.

### D2 — Create a Warehouse
**Warehouses → New warehouse.**
- Code: `WH-TEST`
- Name: `Test Warehouse` → **Save**

✅ Appears in the warehouses list.

### D3 — Create a Product
**Products → New product.** Fill in:
- SKU: `TEST-001`
- Name: `Test Widget`
- Cost price: `10`
- Selling price: `18`
- **Units per carton:** `12`
- **MOQ:** `24`
- Lead time (days): `7`
- Primary supplier: **Test Supplier Co** → **Save**

✅ Appears in the products list with its supplier name shown.

### D4 — Set a starting stock count
**Inventory.** Find your `Test Widget` row (use the search/warehouse filter if needed).
> If the new product isn't listed yet because it has no stock record, that's
> expected — the adjustment below creates one.

Click **Adjust** on that row → in the modal:
- Reason: **Stock count correction**
- Adjustment (+/-): `+50`
- Watch **"New on hand"** update to `50` → **Apply adjustment**

✅ The row now shows 50 on hand / 50 available.

### D5 — Confirm the audit ledger
**Stock Movements.** You should see an **adjustment** row for `Test Widget` at
`WH-TEST`, quantity 50, with a timestamp and your user.

✅ **Proves:** the append‑only movement ledger records every stock change.

### D6 — Create a Purchase Order
**Purchase Orders → New PO.**
- Supplier: **Test Supplier Co** (the currency auto‑fills to USD)
- Warehouse: **Test Warehouse**
- Expected date: pick any near‑future date (optional, but set it — it makes the
  supplier‑performance "on‑time" metric meaningful later)
- Click **Add line** → Product: **Test Widget** → Qty: `30`
  - **Watch:** "Cartons" shows **3** (30 ÷ 12, rounded up) and the line total +
    order total update live.
  - Try Qty `20` briefly → you'll see a **"below MOQ"** warning (MOQ is 24) →
    set it back to `30`.
- **Save draft** → you're taken to the PO detail page, status **draft**.

✅ **Proves:** PO creation, carton math, MOQ visibility, live totals.

### D7 — Move the PO through its lifecycle
On the **PO detail** page, click in sequence (each adds an entry to the timeline):
1. **Submit** → status becomes **pending approval**
2. **Approve** → **approved**
3. **Send** → **sent**

Optionally click **PDF** to render the purchase order document.

✅ **Proves:** the approval state machine and event timeline.

### D8 — Receive the goods (partial, then full)
With the PO **sent**, click **Receive**:
- The quantity pre‑fills to the outstanding amount (30).
- Enter **12** and confirm → status becomes **partially received**.
- Click **Receive** again, accept the remaining **18**, confirm → status **received**.

✅ **Proves:** partial + full receiving and that received quantity flows to stock.

### D9 — Verify the effects of receiving
- **Inventory** → `Test Widget` on‑hand is now **80** (50 start + 30 received).
- **Stock Movements** → new **receipt** rows referencing the PO.
- **Dashboard** → "receipts (30d)" and inventory value have increased.
- **Reports → Supplier performance** → **Test Supplier Co** now shows 1 PO,
  1 received, a fill rate, and (because you set an expected date) an on‑time %.

✅ **Proves:** the full loop — receiving updates stock, the ledger, the dashboard, and supplier analytics.

### D10 — Reorder engine
**Reorder.** Accept the defaults (or tweak the window) → **Run analysis**.
- You'll get recommended quantities. **Expand a line** to see the explanation:
  recommended units, **cartons × units‑per‑carton rounding**, whether **MOQ was
  applied**, the order‑up‑to level, and the demand inputs.
- Optionally tick one or more rows → **Generate POs** → it creates draft PO(s)
  you can then submit/approve/send/receive as above.

✅ **Proves:** demand‑based reordering with carton/MOQ logic → one‑click POs.

### D11 — Reports tour
**Reports.** Click each tab:
- **Valuation** — total cost & retail value, by warehouse and by product.
- **Low stock** / **Out of stock** — items at/under reorder point or at zero.
- **Fast / slow movers** — ranked by average monthly sales (toggle direction).
- **Aging** — on‑hand units bucketed 0‑30 / 31‑60 / 61‑90 / 90+ days (FIFO).

✅ **Proves:** all server‑computed and client‑computed reports render against real data.

### D12 — User management
**Users → New user.**
- Email: `clerk@demo.com`
- Full name: `Test Clerk`
- Password: `ClerkPass123` (must be ≥10 chars with a letter and a digit)
- Tick a limited role if one exists (e.g. a viewer/clerk role); leave Active checked → **Create user**.

Now **log out** (top of the app) and **log back in** as `clerk@demo.com`. Depending
on the role's permissions, you'll see a **reduced sidebar** and some actions hidden.
Log out and back in as admin to continue.

✅ **Proves:** user provisioning, role assignment, and permission‑gated UI.

### D13 — (Optional) Security hardening checks
- **Logout revocation:** after logging out, the old session's refresh token is
  revoked server‑side (not just dropped locally).
- **Login lockout:** ⚠️ **Use the `clerk@demo.com` user for this, NOT admin** —
  a locked account stays locked for ~15 minutes. Enter the **wrong** password
  ~5–6 times in a row → you'll get an "account temporarily locked" message even
  with the right password until the cooldown passes.
- **Rate limiting:** see the API section below for a quick way to trigger a `429`.

---

## 6. Part E — Testing via the API (optional but powerful)

Two ways: the visual Swagger UI, or curl.

### E1 — Swagger UI (easiest)
1. Open http://localhost:8000/docs
2. `POST /api/v1/auth/login` → **Try it out** → body:
   ```json
   { "email": "admin@demo.com", "password": "ChangeMe123!" }
   ```
   → **Execute** → copy the `access_token` from the response.
3. Click the green **Authorize** button (top right) → paste the `access_token` →
   **Authorize** → **Close**. Now every "Try it out" call is authenticated.
4. Explore: `GET /api/v1/products`, `GET /api/v1/inventory`,
   `GET /api/v1/dashboard/metrics`, `GET /api/v1/reports/supplier-performance`, etc.

### E2 — curl (terminal)
```bash
# 1) Log in and capture the access token (requires jq; see no-jq note below)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.com","password":"ChangeMe123!"}' | jq -r .access_token)
echo "$TOKEN"      # should print a long token

# 2) Use it
curl -s http://localhost:8000/api/v1/products -H "Authorization: Bearer $TOKEN" | jq .
curl -s http://localhost:8000/api/v1/dashboard/metrics -H "Authorization: Bearer $TOKEN" | jq .

# Grab seeded IDs to build a PO:
curl -s http://localhost:8000/api/v1/suppliers  -H "Authorization: Bearer $TOKEN" | jq '.items[] | {id,name}'
curl -s http://localhost:8000/api/v1/warehouses -H "Authorization: Bearer $TOKEN" | jq '.items[] | {id,code}'
curl -s http://localhost:8000/api/v1/products   -H "Authorization: Bearer $TOKEN" | jq '.items[] | {id,sku,cost_price}'
```
**No `jq`?** Drop the `| jq ...` part to see raw JSON, and copy the `access_token`
value by hand.

**Create → receive a PO via curl** (replace the `<...>` IDs from the calls above):
```bash
# Create a draft PO
PO=$(curl -s -X POST http://localhost:8000/api/v1/purchase-orders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"supplier_id":"<SUPPLIER_ID>","warehouse_id":"<WAREHOUSE_ID>",
       "lines":[{"product_id":"<PRODUCT_ID>","ordered_qty":"30","unit_cost":"10"}]}')
PO_ID=$(echo "$PO" | jq -r .id)

# Move it through the lifecycle
curl -s -X POST http://localhost:8000/api/v1/purchase-orders/$PO_ID/submit  -H "Authorization: Bearer $TOKEN" -d '{}'
curl -s -X POST http://localhost:8000/api/v1/purchase-orders/$PO_ID/approve -H "Authorization: Bearer $TOKEN" -d '{}'
curl -s -X POST http://localhost:8000/api/v1/purchase-orders/$PO_ID/send    -H "Authorization: Bearer $TOKEN" -d '{}'

# Find the line id, then receive it
curl -s http://localhost:8000/api/v1/purchase-orders/$PO_ID -H "Authorization: Bearer $TOKEN" | jq '.lines[] | {line_id:.id, ordered_qty}'
curl -s -X POST http://localhost:8000/api/v1/purchase-orders/$PO_ID/receipts \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"lines":[{"line_id":"<LINE_ID>","quantity":"30"}]}'
```

### E3 — Trigger the auth rate limit (429)
```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"nobody@demo.com","password":"x"}'
done
```
You should see several `401`s and then `429` (Too Many Requests) once you exceed
the `/auth` limit (default 10/min).

---

## 7. Part F — Run the automated test suite (optional)

The fast **unit tests** need no database. Run them in a Python virtual env:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/unit -q             # pure-logic tests (no DB)
```

To also run the **end-to-end integration tests** (they drive the real app against
the running Postgres from Part A — covering the full warehouse-manager workflow
product→PO→receiving, transfers, and RBAC role enforcement):
```bash
# point the tests at the compose database (app_user/app_pw on localhost:5432)
export DATABASE_URL=postgresql+asyncpg://app_user:app_pw@localhost:5432/inventory   # PowerShell: $env:DATABASE_URL="..."
export JWT_SECRET_KEY=dev-only-change-me-0123456789abcdef0123456789abcdef          # PowerShell: $env:JWT_SECRET_KEY="..."
pytest tests/integration -q     # or just: pytest -q  (runs unit + integration)
```
These create real suppliers/products/POs in the demo database (using unique
names, so they're safe to re-run); `docker compose down -v` resets everything.

> Notes:
> - The API Docker image ships only runtime deps, so `pytest` runs from this
>   local venv rather than inside the container.
> - The **Warehouse Manager** RBAC test asserts the broadened operational
>   permissions. If you're reusing an older database volume, re-seed first
>   (`docker compose down -v && docker compose up`) so the new grants apply.

---

## 8. Part G — Stop / reset

- **Stop the frontend:** `Ctrl‑C` in Terminal 2.
- **Stop the backend (keep data):** `Ctrl‑C` in Terminal 1, then `docker compose stop`.
- **Restart later (same data):** `docker compose up`.
- **Full reset (wipe DB, re‑seed):** `docker compose down -v` then `docker compose up --build`.

---

## 9. Troubleshooting cheat‑sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker: command not found` / "Cannot connect to the Docker daemon" | Docker Desktop not installed/running | Start Docker Desktop; wait for *Running* |
| Compose error: **port 5432 already in use** | Another Postgres is running | Stop it, or change the `db` port mapping to `"5433:5432"` in `docker-compose.yml` |
| Compose error: **port 8000 already in use** | Something else on 8000 | Stop it, or change the `api` ports to `"8001:8000"` (then use `:8001`) |
| **Login fails** with correct password | Stale database volume from an older build | `docker compose down -v && docker compose up --build` |
| `npm run build` prints **TypeScript errors** | A type issue I couldn't run here | Copy the full output and send it to me |
| Frontend loads but every call fails / **CORS** error | Backend not up, or wrong API URL | Confirm http://localhost:8000/health works; check `frontend/.env` is `http://localhost:8000/api/v1` |
| **Port 5173 in use** | Another Vite app | `npm run dev -- --port 5174` and open `:5174` |
| Blank white page | dev server not restarted after `.env` change | `Ctrl‑C` then `npm run dev` again |
| `401 Unauthorized` in Swagger | Token not set / expired | Re‑run login, click **Authorize**, paste a fresh `access_token` |
| Supplier‑performance shows "—" | No fully‑received POs yet | Complete D6–D8 first |

---

## 10. If something breaks — what to send me

Paste whichever applies and I'll pinpoint the fix fast:
1. **The exact command** you ran and the **full error text**.
2. **Backend issues:** `docker compose logs api --tail=80` (and `... logs db --tail=40`).
3. **Frontend build issues:** the complete `npm run build` output.
4. **Runtime API errors in the browser:** the failing request's status + response
   (DevTools → Network tab), plus the matching lines from `docker compose logs api`.

That's it — work through Parts A→D and you'll have exercised the entire system end
to end. When you're ready to continue building, tell me what (if anything) broke.
