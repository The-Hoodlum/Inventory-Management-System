# Supply Chain Intelligence Platform — Architecture & Roadmap

> Status: living document. Reflects the platform **as built through Phase D**
> (operational core + demand pipeline + deterministic forecasting + provider/
> signal extension seams) and the **target architecture** for the AI-powered
> Supply Chain Intelligence Platform.
>
> Audience: engineering, future hires, and technical due-diligence. Read
> alongside `database/sql/schema.sql` (data model source of truth) and
> `backend/REORDER_ENGINE.md` / `backend/PROCUREMENT_MODULE.md`.

---

## 1. Purpose & scope

The platform helps procurement-intensive businesses (importers, distributors,
wholesalers, dealerships, spare-parts, logistics, manufacturers, e-commerce)
answer: **what to order, how much, when, from whom, and at what risk.** It is
built industry-agnostic; vertical workflows layer on later without redesign.

The product matures in layers — **operational excellence first, intelligence
second, AI last** — because advanced forecasting and AI are only as good as the
stable, auditable workflows and clean demand data beneath them.

---

## 2. Architectural principles

These are the rules that keep the system evolvable. New code is expected to obey
them; deviations should be justified in review.

1. **Pure domain at the core.** Business math (reorder policy, PO state machine,
   receiving, forecasting) lives in dependency-free, unit-tested modules
   (`app/*/domain/`). No framework, no I/O. This is the company's IP and must
   stay testable in isolation.
2. **The dependency rule points inward.** `api → service → repository → domain`.
   Inner layers never import outer ones. Domains may depend on other *domains*
   one-directionally (e.g. reorder consumes a forecast signal) but never on
   services/repositories.
3. **One source of truth per concept.** Demand lives in `sales_daily`. PO
   creation has a single path (`ProcurementService.create_po`). Safety-stock /
   reorder-point / order-quantity math lives only in `reorder/domain`. The
   forecast engine produces a *demand signal*; it does **not** re-derive reorder
   levels.
4. **Money & quantities are `Decimal` / `NUMERIC`, never float.**
5. **Multi-tenant by construction.** Every business table carries `tenant_id`
   and is under PostgreSQL Row-Level Security; the app connects as a
   non-superuser so RLS is enforced even against bugs.
6. **Append-only truth, derived balances.** `stock_movements` is the immutable
   ledger; `inventory` is the maintained running balance. Forecasts are stored
   immutably for accuracy tracking.
7. **Extend by registration, not modification.** Forecast methods and
   intelligence signals plug into registries; adding one must not touch the
   core (see §7).
8. **Optional intelligence.** Forecasting and signals are opt-in. The platform
   runs correctly with them switched off (historical demand, no signals).

---

## 3. System context & tech stack

```
        ┌─────────────┐        HTTPS/JWT        ┌───────────────────────────┐
        │  React SPA  │ ───────────────────────▶│  FastAPI (async) backend  │
        │ (Vite/TS)   │ ◀─────────────────────── │  RBAC · RLS · rate limit  │
        └─────────────┘                          └────────────┬──────────────┘
                                                              │ asyncpg
                                                  ┌───────────▼─────────────┐
                                                  │  PostgreSQL 16          │
                                                  │  RLS · ledger · forecasts│
                                                  └─────────────────────────┘
   Future (Phase 3+): external intelligence feeds (freight, port, FX, commodity,
   trade, geopolitical) → ingested as *signals* (see §7.3).
```

- **Backend:** Python 3.11+, FastAPI, async SQLAlchemy 2.0, asyncpg, Pydantic v2,
  PyJWT, bcrypt, fpdf2. Packaged via Docker.
- **Frontend:** React 18, Vite, TypeScript, Tailwind, TanStack Query.
- **DB:** PostgreSQL 16 (pgcrypto, pg_trgm, citext), Alembic migrations that
  execute the canonical SQL files.

---

## 4. Layered architecture

```
            ┌──────────────────────── API (FastAPI routers) ────────────────────────┐
            │  auth · products · suppliers · warehouses · inventory · purchase-orders │
            │  reorder · demand · forecast · reports · dashboard · users              │
            └───────────────▲───────────────────────────────────────────────────────┘
                            │ depends on (RBAC + RLS tenant scoping set here)
            ┌───────────────┴──────────────── Services (orchestration) ──────────────┐
            │  AuthService · InventoryService · ProcurementService · ReorderService   │
            │  DemandService · ForecastService · ReportsService · DashboardService    │
            └───────────────▲───────────────────────────────────────────────────────┘
                            │ uses
            ┌───────────────┴──────────────── Repositories (the only DB layer) ───────┐
            │  one per aggregate; tenant scoping via RLS GUC, not WHERE clauses        │
            └───────────────▲───────────────────────────────────────────────────────┘
                            │ persists / reconstructs
            ┌───────────────┴──────────────── Pure domain (no I/O, unit-tested) ───────┐
            │  reorder/domain (engine, rounding, safety_stock, models)                 │
            │  procurement/domain (state machine, receiving)                           │
            │  forecast/domain (methods, providers, signals, confidence, accuracy)     │
            └─────────────────────────────────────────────────────────────────────────┘
```

**Request/transaction model.** `get_db` opens one transaction per request.
`get_current_user` validates the JWT and sets `app.current_tenant`
*transaction-locally*, so RLS scopes every subsequent query and the setting is
cleared automatically when the transaction ends — no leakage across the pool.

---

## 5. Module map (current)

| Module | Responsibility | Key extension seam |
|---|---|---|
| `auth` / identity | JWT (rotation + reuse detection), RBAC, lockout, audit | roles/permissions are data |
| `catalog` | products, suppliers, categories, brands, supplier_products | per-supplier sourcing |
| `inventory` | receive/issue/adjust/transfer, ledger, valuation | movement types |
| `procurement` | **single PO creation path**, lifecycle state machine, receiving, PDF, email | PO event timeline |
| `reorder` | (s,S) policy engine; historical **or** forecast-driven demand | demand mode |
| `demand` | rolls outbound issues → `sales_daily`; canonical `daily_series` | **demand sources** (§7.1) |
| `forecast` | deterministic forecasting, persistence, accuracy, dashboard | **providers** (§7.2) + **signals** (§7.3) |
| `intelligence` | supply-chain intelligence: ingestion providers, risk scoring, dashboard; feeds the forecast signal pipeline | **ingestion providers** + **ExternalSource** adapters |
| `reports` | inventory aging (FIFO), supplier performance | new report computations |
| `dashboard` | operational KPIs | new metrics |

---

## 6. Data model (essentials)

- **Tenancy/identity:** `tenants`, `users`, `roles`, `permissions`, `role_permissions`,
  `user_roles`, `refresh_sessions`, `audit_logs`. Identity tables are
  intentionally *not* under RLS (login resolves tenant before any GUC exists);
  isolation is enforced by `(tenant_id, …)` keys + the repository layer.
- **Catalog:** `products` (incl. pallet/container fields stored from day one),
  `suppliers`, `supplier_products` (multi-sourcing), `categories`, `brands`.
- **Stock:** `inventory` (with a generated `qty_available` column),
  `stock_movements` (append-only signed ledger).
- **Demand:** `sales_daily` — one row per `(product, warehouse, date, source)`.
  The `source` tag (`issue|import|pos|manual`) lets multiple channels coexist;
  demand reads `SUM(qty_sold)` per day across sources.
- **Procurement:** `purchase_orders`, `purchase_order_lines`,
  `purchase_order_events` (lifecycle timeline), `po_counters`,
  `reorder_recommendations`.
- **Forecasting:** `demand_forecasts` — stores each forecast with both
  `daily_demand` (base) and `adjusted_daily_demand` (post-signal) plus a
  `risk_score`, so the intelligence layer writes here with **no schema change**.

All business tables: `tenant_id` + RLS policy + `app_user` grant. Additive
changes ship as idempotent SQL files (`database/sql/*.sql`) executed both on
fresh init (docker-compose) and by a matching Alembic migration.

---

## 7. The three extension seams (the heart of evolvability)

The platform is designed so the entire Supply Chain Intelligence vision can be
built by **adding** to three registries — never by rewriting the core.

### 7.1 Demand sources → feed `sales_daily`

`sales_daily.source` + the `(product, warehouse, date, source)` key let any
channel contribute demand. Today: `DemandRepository.aggregate_issues` writes
`source='issue'` from the stock ledger (idempotent recompute-and-upsert).

**To add a source (CSV import, POS, ERP, Shopify):** write a new repository/
service that upserts rows under a new `source` tag. Forecasting and reorder read
the per-day **sum across sources** via `DemandRepository.daily_series` — they do
not change.

### 7.2 Forecast providers → `app/forecast/domain/providers.py`

A `ForecastProvider` turns a daily series into a `ForecastResult`. Providers
self-register in a keyed registry; the service, API (`GET /forecast/providers`),
and reorder engine all work through it.

Built-in (deterministic, no ML): `moving_average`, `exponential_smoothing`.

**To add a method (Croston / Seasonal / Holt-Winters / ML):**

```python
class CrostonProvider(ForecastProvider):
    key, label = "croston", "Croston (intermittent demand)"
    def generate(self, series, params):
        point = ...                      # method-specific point estimate
        return package_result(series, point, ForecastMethod.CROSTON)

register_provider(CrostonProvider())     # nothing else changes
```

The result packaging (variability, confidence, stats) is shared, so a new method
only supplies a point estimate. ML providers follow the same contract — the
model lives behind the provider; the platform stays method-agnostic.

### 7.3 Intelligence signals → `app/forecast/domain/signals.py`  *(Phase 3 built on this seam — see §12)*

A `ForecastSignal` is an external-intelligence input that **adjusts demand
(multiplicative factor) and contributes to a 0–1 supply-risk score.** The
`SignalPipeline` composes all registered signals over a base forecast. **Today
there are zero signals, so it is a transparent pass-through** — but the seam is
wired through persistence (`adjusted_daily_demand`, `risk_score`), the forecast
API, and reorder (forecast mode uses the *adjusted* demand).

Planned categories (Phase 3), each a future module that calls `register_signal`:

| Category | Example effect |
|---|---|
| `supplier` | reliability/financial health → risk; demand pull-forward |
| `freight` | ocean/air cost & capacity pressure → risk |
| `port` | congestion / dwell time → longer effective lead time |
| `commodity` | raw-material price moves → cost/risk |
| `trade` | tariffs, quotas, customs → cost/availability |
| `geopolitical` | conflict, sanctions, strikes, weather → risk |

```python
class PortCongestionSignal(ForecastSignal):
    key, category = "port_congestion", SignalCategory.PORT.value
    def evaluate(self, ctx: SignalContext) -> SignalAdjustment | None:
        delay = lookup_congestion(ctx.warehouse_id)          # external feed
        if not delay: return None
        return SignalAdjustment(source=self.key, category=self.category,
                                demand_factor=Decimal("1.0"),
                                risk_delta=Decimal("0.2"),
                                reason=f"+{delay}d port dwell")

register_signal(PortCongestionSignal())   # forecasting core untouched
```

Because reorder forecast-mode and stored forecasts already consume the adjusted
output, **registering a signal immediately improves recommendations and risk
scoring everywhere — with no change to the forecasting, reorder, or persistence
code.**

---

## 8. Demand → Forecast → Reorder → PO data flow

```mermaid
flowchart LR
    SM[stock_movements\n(issue outflows)] -->|DemandService.aggregate_issues\n(idempotent)| SD[(sales_daily\nby source)]
    IMP[CSV / POS / ERP\n(future sources)] -.->|upsert source tag| SD
    SD -->|daily_series\n(sum across sources)| SER[dense daily series]
    SER --> PROV{Forecast provider\n(registry)}
    PROV --> BASE[base ForecastResult]
    BASE --> PIPE{Signal pipeline\n(empty today)}
    SIG[Intelligence signals\n(future)] -.-> PIPE
    PIPE --> ADJ[adjusted demand + risk_score]
    ADJ --> FC[(demand_forecasts)]
    ADJ -->|reorder demand_mode=forecast| ENG[Reorder engine\n(s,S policy)]
    SD -->|reorder demand_mode=historical| ENG
    ENG --> REC[reorder_recommendations]
    REC -->|ReorderService.create_purchase_orders| PO[ProcurementService.create_po\n(single PO path)]
    PO --> POE[(purchase_orders\n+ events + audit)]
```

**Reorder demand modes (optional intelligence):**
- `historical` (default) — window mean/variance straight from `sales_daily`.
- `forecast` — runs a provider over the same series, through the signal
  pipeline, and feeds the *adjusted* daily demand into the unchanged (s,S)
  engine.

---

## 9. Risk scoring model

- **Today:** `risk_score = 0` for every forecast (no signals registered). The
  field exists and is persisted so history is comparable once signals arrive.
- **Future:** each signal contributes an additive `risk_delta`; the pipeline
  sums and clamps to `[0,1]`. Risk will drive: recommendation prioritisation,
  dashboard "supply at risk" views, larger safety buffers for high-risk items,
  and (Phase 4) the AI advisor's confidence/risk commentary.
- **Design intent:** keep risk *explainable* — every contribution carries a
  `source`, `category`, and human-readable `reason`.

---

## 10. Security & multi-tenancy

- JWT access tokens (short-lived) + server-side refresh sessions with rotation,
  reuse detection, and family revocation.
- bcrypt(12) password hashing; login lockout via pure, tested policy.
- RBAC: permission codes mirror the SQL seed; enforced by `require_permission`.
- PostgreSQL RLS with `FORCE ROW LEVEL SECURITY`; app runs as a non-superuser.
- Edge: per-IP rate limiting, security headers, optional HTTPS redirect/HSTS.
- Audit: every mutation writes `audit_logs`; PO lifecycle also writes
  `purchase_order_events`.

---

## 11. Known debt & operational concerns (carried forward)

Tracked from the 2026-06 audit; not blockers for the current milestone but
required before scale:

- **Rate limiter is in-memory** — needs Redis for multi-instance.
- **No CI pipeline yet** — 170+ unit tests exist; add lint + unit on every push
  and integration against an ephemeral Postgres.
- **No self-serve tenant onboarding** — tenants are provisioned by seed/migration.
- **Reorder/forecast bulk loops are O(products × warehouses)** — fine for
  hundreds; move to set-based queries before large catalogs.
- **Reservation/allocation unimplemented** — `qty_reserved`/`qty_damaged` exist
  but no service writes them yet.
- **PO email + PDF run inside the request transaction** — move to a background
  worker/queue.
- **Multi-currency not consolidated** in dashboard/report rollups.
- **No cross-tenant RLS isolation integration test** — add to protect the
  security cornerstone.
- **Local dev on Python 3.14** can't compile `asyncpg`/`bcrypt` without MSVC;
  full-suite + integration verification runs in Docker
  (`docker compose run --rm api pytest -q`).

---

## 12. Roadmap

Mapping the product vision to delivery. ✅ done · 🟡 partial · ⬜ planned.

### Phase 1 — Operational Excellence  ✅ (hardening continues)
Inventory, warehouses, procurement, receiving, reporting, dashboards, auth/RBAC,
multi-tenancy. **Single PO creation path** unified in this cycle.

### Phase 2 — Procurement Intelligence  🟡 (foundation delivered)
- ✅ **Demand pipeline** (issues → `sales_daily`, multi-source ready).
- ✅ **Deterministic forecasting** (moving average, exponential smoothing) behind
  a **provider registry**; confidence scoring; **forecast-vs-actual accuracy**.
- ✅ **Forecast persistence + APIs + dashboard summary**.
- ✅ **Forecast-driven reorder mode** (optional; historical remains default).
- ⬜ Additional providers: Croston (intermittent), Seasonal/Holt-Winters, ML.
- ⬜ Supplier scoring & lead-time prediction surfaced into reorder.
- ⬜ Stockout prediction & reorder optimisation tuning.

### Phase 3 — Supply Chain Intelligence  🟡 (data layer + first providers delivered)
- ✅ **Intelligence data layer** — `intelligence_signals` table (normalised
  observations: severity, demand_factor, confidence, scope, expiry) + repository
  + service + API (migration `0007`).
- ✅ **Supplier Risk provider** — *fully functional*, computed from PO history
  (on-time rate, lead-time mean/variance, fill rate → 0..1 risk).
- ✅ **Freight / Port / Commodity / Trade providers** — real providers with an
  `ExternalSource` adapter seam (Freightos/Xeneta/commodity/customs APIs plug in
  here) plus a working **manual-entry** ingestion path; no-ops until a source is
  configured.
- ✅ **Pipeline bridge** — `IntelligenceForecastSignal` registered into the
  forecast `SignalPipeline`; matches global/supplier/country scopes and feeds an
  adjusted demand + risk score. Proven end-to-end via `/intelligence/impact`.
- ✅ **Intelligence dashboard** — `/intelligence/dashboard`: overall risk,
  forecast impact, confidence, per-category breakdown, recommended actions, drivers.
- ✅ **Risk-aware procurement & forecasting** — intelligence now *moves the
  numbers*, not just the dashboard:
  - reorder engine takes an optional `RiskAdjustment` (pure, tested): risk raises
    **safety stock** (multiplier) and **reorder point** (longer effective lead +
    SS uplift; a manual override stays a floor with risk added on top), flags
    **expedite** (order earlier), and the service computes the **financial
    impact** (extra units × unit cost) and records **which signals contributed**
    (`risk_drivers`). Persisted on `reorder_recommendations` (migration `0008`).
  - lead-time risk is sourced only from supply-delaying categories (freight,
    port, geopolitical); overall risk drives the safety-stock buffer.
  - forecasts attach the intelligence snapshot, so stored forecasts carry an
    adjusted demand + risk score per SKU's supplier.
- ⬜ Real external-source adapters (need vendor API credentials); scheduled
  ingestion; product↔commodity tagging for commodity matching.

The original design held: every provider feeds the **existing** pipeline; no
forecast-core change was needed to add intelligence, and risk entered the reorder
engine as a typed value object without disturbing its tested core.

### Phase 4 — AI Procurement Advisor  ⬜
Natural-language: "What should I order this week?" The advisor composes the
*already-structured* outputs (forecasts, recommendations, supplier metrics, risk
scores) into an explainable answer with quantities, suppliers, risks, confidence,
and cost impact. LLM sits **on top of** deterministic engines — it explains and
recommends, it does not compute the numbers.

### Phase 5 — Container Optimisation  ⬜
Optimise MOQ, cartons, weight, volume, budget, and forecast demand to maximise
container utilisation and profitability. The pallet/container fields already on
`products` feed this; output plugs into PO generation.

---

## 13. Extension cookbook (quick reference)

| Want to… | Do this | Touches core? |
|---|---|---|
| Add a demand channel | new upsert into `sales_daily` with a new `source` | No |
| Add a forecast method | subclass `ForecastProvider`, `register_provider(...)` | No |
| Add an intelligence signal | subclass `ForecastSignal`, `register_signal(...)` | No |
| Add a reorder safety-stock method | extend `reorder/domain/safety_stock.py` + `SafetyStockMethod` | reorder domain only |
| Add a report | pure compute in `reports/compute.py` + service/repo | No |
| Add a permission | seed it (RBAC migration) + add to `core/permissions.py` | No |

---

## 14. Glossary

- **(s, S) policy** — reorder when inventory position ≤ reorder point `s`; order
  up to level `S`.
- **Inventory position** — available stock + on-order (open POs).
- **Demand signal** — expected daily demand + variability + confidence produced
  by the forecast engine; *input* to the reorder engine.
- **Intelligence signal** — external input that adjusts a forecast and risk
  score (Phase 3+).
- **Source (demand)** — the channel a `sales_daily` row came from
  (`issue|import|pos|manual`).
- **Risk score** — explainable 0–1 supply-risk aggregate from signals.
