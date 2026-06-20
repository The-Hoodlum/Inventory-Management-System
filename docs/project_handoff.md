# Project Handoff — Inventory, Procurement & Supply Chain Intelligence Platform

> **Date:** 2026-06-14 · **Status:** active development · **Audience:** incoming engineers / technical owner.
> Companion docs: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) (deep architecture + extension seams),
> `backend/REORDER_ENGINE.md`, `backend/PROCUREMENT_MODULE.md`, `Inventory_Procurement_Platform_Blueprint.md`.
> Database source of truth: `database/sql/schema.sql` + the additive `database/sql/*.sql` files.

---

## 1. Current architecture

A multi-tenant SaaS evolving from operational inventory/procurement into **Supply Chain Intelligence + Procurement + Forecasting + AI decision support**.

**Stack**
- **Backend:** Python 3.11+, FastAPI, async SQLAlchemy 2.0, asyncpg, Pydantic v2, PyJWT, bcrypt, fpdf2, httpx. Packaged with Docker.
- **Frontend:** React 18 + Vite + TypeScript + Tailwind + TanStack Query.
- **DB:** PostgreSQL 16 (pgcrypto, pg_trgm, citext), Alembic migrations that execute canonical SQL.

**Layering (strict, dependency points inward):** `api → service → repository → pure domain`. Pure domain modules (`app/*/domain/`, `app/catalog/profile.py`) have no framework/DB imports and are unit-tested in isolation. Multi-tenant isolation via PostgreSQL **Row-Level Security**; the app connects as a non-superuser so RLS is enforced. One DB transaction per request; the tenant GUC (`app.current_tenant`) is set transaction-locally.

**Module map (`backend/app/`)**

| Module | Responsibility |
|---|---|
| `core` | config, security (JWT rotation+reuse detection), RBAC, rate limit, logging, exceptions |
| `models` | ORM (catalog, identity, inventory, procurement, intelligence) |
| `catalog` | **pure `ProductProfile`** value object + vulnerability/forecast-method helpers |
| `inventory` / repositories | receive/issue/adjust/transfer, append-only ledger, valuation |
| `procurement` | single PO creation path, lifecycle state machine, receiving, PDF, email |
| `reorder` | (s,S) engine + **risk overlay** (pure `domain/risk.py`), historical/forecast demand modes |
| `forecast` | provider registry (MA / exp-smoothing / Croston / seasonal), demand-pattern detection (`domain/patterns.py`), accuracy/MAPE, signal pipeline, persistence |
| `container` | **pure** container load planning (`domain/planning.py`): 20GP/40GP/40HC specs, volume+weight utilisation, binding constraint, container recommendation, MOQ-aware top-off |
| `advisor` | **AI Supply Chain Analyst** (Phase 10): deterministic, explainable **briefing** (`domain/briefing.py`) grounding findings in real reorder / signal / supplier / forecast / **container-load** data + an **inert-by-default LLM seam** (`domain/llm.py`, `providers.py`) that only narrates the grounded findings |
| `demand` | rolls outbound `issue` movements → `sales_daily`; canonical daily series |
| `intelligence` | signals data layer, providers (computed + **6 free HTTP feeds** in `providers/external.py` via `providers/registry.py`), scoring, supplier scorecards, dashboard, external `sources/` (paid), **daily `scheduler.py`** |
| `dashboard` / `reports` | operational KPIs; FIFO inventory aging + supplier performance |

**Three extension seams** (documented in `ARCHITECTURE.md`): demand sources (`sales_daily.source`), forecast providers (registry), and intelligence signals (`SignalPipeline`). Adding a method/source/signal is registration, not core modification.

---

## 2. Completed phases

| # | Capability | Migrations | State |
|---|---|---|---|
| 1 | **Operational core** — inventory, warehouses, products, suppliers, purchase orders (full lifecycle + PDF/email), reorder engine | 0001–0004 | ✅ |
| 2 | **Forecasting + demand pipeline** — deterministic providers (moving average, exponential smoothing), confidence, accuracy/MAPE, forecast persistence, demand rollup from issues | 0005, 0006 | ✅ |
| 3 | **Supply-chain intelligence data layer** — `intelligence_signals`, providers (supplier risk computed; freight/port/commodity/trade feed-shaped), probabilistic-OR risk scoring, SignalPipeline, intelligence dashboard | 0007 | ✅ |
| 4 | **Risk-aware reordering + Intelligence Dashboard UI** — intelligence amplifies safety stock / reorder point / order timing; expedite flags; financial impact; first React intelligence screen | 0008 | ✅ |
| 5 | **Product Intelligence Profile** — structured product attributes consumed by risk + forecast + intelligence matching | 0009 | ✅ |
| 6 | **Supplier Intelligence** — persisted, intelligence-blended supplier scorecards | 0010 | ✅ |
| 7 | **Forecast Intelligence** — demand-pattern detection (ADI/CV² SBC classification, trend, seasonality), Croston + seasonal-decomposition providers, per-product `auto` method selection, `POST /forecast/analyze` | (none) | ✅ |
| 8a | **Freightos credential/config support** — env-driven key+secret, startup validation, inert-by-default `ExternalSource` | (none) | ⚠️ config done; live auth unresolved (see §8) |
| 9 | **Container Optimization** — deterministic 20GP/40GP/40HC load planning from carton dims: volume+weight utilisation, binding constraint, best-container recommendation, MOQ-aware top-off; `GET /container/containers`, `POST /container/plan` | (none) | ✅ |
| 10 | **AI Supply Chain Analyst (foundation)** — deterministic, explainable advisory briefing grounding findings in real reorder/signal/supplier/forecast data; config-gated, inert-by-default Claude narrator (`claude-opus-4-8`) that only narrates the grounded findings; `GET /advisor/briefing` | (none) | ✅ foundation done; live LLM narration awaits a key (see §8/§9) |
| 8b | **Production intelligence feeds + scheduler** — generalized `HttpIntelligenceProvider` + registry; 6 free providers (ExchangeRate.host, World Bank, IMF, UN Comtrade, GDELT, OpenWeather) mapping public APIs → signals in existing categories; daily multi-tenant scheduler (ingest → risk → supplier scores). All inert by default; paid providers plug into the same registry. Verified live (World Bank cycle ingested 118 signals across 2 tenants). | (none) | ✅ |

**Tests:** **full suite green in Docker (exit 0) — 376 tests (365 unit + 11 integration)** on a fresh DB, including a **cross-tenant RLS isolation test** (§13) that proves PostgreSQL Row-Level Security keeps tenants separated over the API. App boot verified in-container (full import graph; `/forecast/analyze` and `/container/*` register). The integration suite's event-loop harness bug and the two reorder/API bugs it had been masking are fixed (see §13).

---

## 3. Database schema changes (migrations)

All additive migrations execute an idempotent SQL file and have reversible `downgrade()`. **Two provisioning paths, same result:** an existing DB applies the 10 revisions below via `alembic upgrade head`; a fresh Docker DB runs **12 ordered init scripts** mounted in `docker-compose.yml` — the 10 schema migrations **plus** two non-migration scripts: `02_app_role.sql` (creates the non-superuser `app_user` role + grants that make RLS enforceable) and `04_seed_demo.sql` (optional demo data — now **two tenants**, `demo` + `globex`, for multi-tenant isolation; dev/eval only — never load into production).

| Rev | File | Adds |
|---|---|---|
| 0001 | `schema.sql` | Full base schema: tenants, users/roles/permissions, catalog, inventory + `stock_movements` ledger, `sales_daily`, purchase orders/lines, `reorder_recommendations`, RLS policies |
| 0002 | `seed_rbac.sql` | RBAC roles + permission seed |
| 0003 | `po_events.sql` | `purchase_order_events` lifecycle timeline |
| 0004 | `auth_hardening.sql` | login lockout columns + `refresh_sessions` (rotation/reuse detection) |
| 0005 | `demand_source.sql` | `sales_daily.source` + `(product,warehouse,date,source)` key (multi-source demand) |
| 0006 | `demand_forecasts.sql` | `demand_forecasts` (stored forecasts + risk_score for accuracy tracking) |
| 0007 | `intelligence.sql` | `intelligence_signals` (normalised observations across all categories) |
| 0008 | `reorder_risk.sql` | risk columns on `reorder_recommendations` (risk_score, lead_time_extra_days, risk_cost_impact, expedite, risk_drivers) |
| 0009 | `product_profile.sql` | products: `commodity_tags`(JSONB), `country_of_origin`, `transport_mode`, `criticality`, `supplier_dependency`, `demand_type`, `substitutability` + GIN index |
| 0010 | `supplier_scores.sql` | `supplier_scores` (persisted supplier scorecards, intelligence-blended) |

Every business table carries `tenant_id` + an RLS `tenant_isolation` policy + `app_user` grants.

---

## 4. Intelligence modules

- **Data layer** — `intelligence_signals` rows: `category` (freight/port/commodity/trade/supplier/geopolitical), `scope_type` (global/country/supplier/commodity/route/port), severity, demand_factor, confidence, headline, value/trend, source, `expires_at`.
- **Scoring** (`domain/scoring.py`, pure) — probabilistic-OR risk aggregation `1 − Π(1 − severityᵢ)`, composite demand factor, confidence, per-category breakdown, rule-based recommended actions.
- **Providers** (`providers/`) — `SupplierRiskProvider` (**real**, computed from PO history) + freight/port/commodity/trade feed providers behind the `ExternalSource` interface (inert until a vendor source is configured).
- **Signal pipeline bridge** (`signals.py`) — `IntelligenceForecastSignal` registered into the forecast `SignalPipeline`; snapshot matches **global + supplier + supplier-country + product commodity tags + product origin country**.
- **Supplier scorecards** (`domain/supplier_score.py`) — blends internal performance risk with active supplier/country signals.
- **External sources** (`sources/`) — `FreightosSource` + `build_external_source(settings)` factory (NullSource when unconfigured).
- **Production feeds** (`providers/external.py` + `providers/registry.py`) — `HttpIntelligenceProvider` base (config-gated, defensive fetch, pure parser) with 6 free providers, each mapping a public API to signals in existing categories scoped for matching: **ExchangeRate.host** (FX→trade/country), **World Bank** (GDP growth→geopolitical/country), **IMF** (inflation→trade/country), **UN Comtrade** (trade flows→trade), **GDELT** (disruption news→geopolitical/global), **OpenWeather** (severe weather→port/country). All inert until enabled; `build_free_providers(settings)` returns only the enabled ones and feeds them to `IntelligenceService` via `extra_providers`. Paid providers (Freightos/Xeneta/Trading Economics) plug into the same registry with **no engine change**.
- **Scheduler** (`scheduler.py`) — config-gated daily job (`INTEL_SCHEDULER_ENABLED`) that, per tenant (own RLS GUC), ingests every enabled provider then refreshes supplier scores; signals then feed risk/forecast/reorder via the existing pipeline. Per-tenant/per-cycle errors are isolated. Started from the app lifespan; off by default.
- **Dashboard + API** — risk score, forecast impact, recommended actions, confidence; pipeline-impact endpoint proves intelligence flows through the real pipeline.
- **No fabricated data:** providers return nothing unless real internal data or a configured external feed exists.

---

## 5. Product Intelligence status — ✅ DONE (Phase 5, migration 0009)

- Products carry `commodity_tags`, `country_of_origin`, `transport_mode`, `criticality`, `supplier_dependency`, `demand_type`, `substitutability` (carton dims reuse existing `volume_per_carton`/`weight_per_carton`).
- Pure `ProductProfile` (`app/catalog/profile.py`) with `vulnerability()` (risk amplifier from criticality/sourcing/substitutability) and `suggested_forecast_method()` (from demand type).
- **Consumed live:** commodity signals now bind to SKUs via `commodity_tags`; country signals bind via `country_of_origin`; risk amplified by product vulnerability in the reorder engine; forecast provider defaults from `demand_type`.
- Exposed through product create/update/out schemas + API.

---

## 6. Supplier Intelligence status — ✅ DONE (Phase 6, migration 0010)

- `supplier_scores` table; pure `SupplierScorecard` + `build_scorecard`.
- Tracks: **Reliability, Lead-Time Accuracy** (1 − lead-time CoV), **Delivery Performance** (on-time rate), **Fill Rate**, **Purchase History** (po_count, received_po_count, total_spend, last_order_at), **Risk Score** (blended) + letter grade A–F + drivers.
- **Blends intelligence:** `performance_risk` (internal, from `supplier_risk`) ⊕ `intelligence_risk` (active supplier/country signals, probabilistic-OR). Supplier-specific signals only (`include_global=False`).
- APIs: `POST /intelligence/suppliers/refresh`, `GET /intelligence/suppliers`, `GET /intelligence/suppliers/{id}` (latest + history).
- History retained per recompute (trendable).

---

## 7. Forecast Intelligence status — ✅ DONE (Phase 7, no migration)

- ✅ **Foundation (earlier):** provider registry, moving-average + exponential-smoothing providers, confidence score, **forecast accuracy / MAPE / forecast-vs-actual** (`forecast/domain/accuracy.py` + `GET /forecast/{id}/accuracy`), forecast persistence + dashboard summary, optional forecast-driven reorder mode.
- ✅ **Detection** (`forecast/domain/patterns.py`, pure): **ADI** + **CV²** of demand sizes → **Syntetos-Boylan-Croston** classification (smooth/erratic/intermittent/lumpy); **trend** via least-squares slope (direction + 0..1 strength); **seasonality** via autocorrelation of the *detrended* series (period + strength). `analyze()` returns a `DemandPattern` whose `suggested_demand_type` speaks the `DemandType` vocabulary and whose `suggested_method` is a provider key.
- ✅ **Providers:** `croston` (intermittent — size/interval smoothing, mean-seeded so it's insensitive to window alignment) and `seasonal` (classical multiplicative decomposition: indices → deseasonalise → level+trend → reseasonalised horizon average, the explainable cousin of Holt-Winters). Both reuse `package_result`; the single-scalar `ForecastResult` contract is unchanged (no persistence/reorder ripple).
- ✅ **Consumption:** `catalog/profile.py` now maps `intermittent`/`lumpy` → `croston`, `seasonal` → `seasonal`, so the **reorder forecast mode picks them automatically** via `suggested_forecast_method(demand_type)` (no reorder change). `POST /forecast/run` accepts `method:"auto"` to detect the best method **per product**; `POST /forecast/analyze` returns a product's measured `DemandPattern` for explainability / demand_type recommendation.
- The Syntetos-Boylan (SBA) bias correction for Croston and a full per-day forward seasonal vector (would require extending `ForecastResult` + persistence + reorder) are noted future refinements, deliberately out of scope to keep the contract stable.

---

## 8. Freightos integration status — ⚠️ CONFIG DONE, AUTH UNRESOLVED

**What works**
- Credential management is env-driven (`FREIGHTOS_API_KEY` + `FREIGHTOS_API_SECRET`), requires **both**, with **startup validation** (`main._validate_freightos` → raises in production, warns otherwise) that logs only missing field *names*.
- Secrets never logged, never exposed via any API; `FreightosSource.__repr__` is redacted.
- `ExternalSource` seam + factory; inert (no network) unless `freightos_configured`.
- **Endpoint corrected and verified:** `POST https://api.freightos.com/api/v1/co2calc` (config + compose + `.env.example` updated). A live probe returns `401` with a `{"messages":…}` envelope — i.e. the path/method/network are correct; only auth remains.

**Blocked / open**
- **Authentication not yet accepted.** Live probe results: `basic` → 401, `x-api-key`/`x-api-secret` headers → 401, `oauth2` **untested** (default token URL `…/oauth/token` returned 404 — wrong token endpoint). Credentials are **not confirmed invalid** — this is a credential-presentation/mode problem. Most likely OAuth2 client-credentials with a token URL we don't have yet.
- **Needed (non-secret):** from the Freightos CO2 API auth docs — the auth scheme (OAuth2 / API-key header / Basic), the **token endpoint URL** if OAuth2, and the exact **header name** if API-key.
- **Adapter mismatch (design):** `/co2calc` is a CO2-emissions **calculator** (POST a shipment → emissions), not a freight-rate feed. `FreightosSource` is currently shaped as a GET rate-index → risk signal. Once auth works, it needs a POST + request-body path and a CO2-appropriate normalization (emissions/ESG or cost proxy ≠ rate-change risk).

---

## 9. Environment variables

Backend reads `backend/.env`; Docker reads root `.env` and passes vars to the `api` container (see `docker-compose.yml`). Full templates: `backend/.env.example`, root `.env.example`. **Never commit real secrets.**

**Core:** `ENVIRONMENT`, `DEBUG`, `API_V1_PREFIX`, `DATABASE_URL` (async `postgresql+asyncpg://`), `DB_POOL_SIZE`, `JWT_SECRET_KEY` (app refuses to boot on default in production), `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, lockout settings, `CORS_ORIGINS`, rate-limit/security-header/HSTS settings, `LOG_LEVEL`, `LOG_JSON`, SMTP settings, company identity (`COMPANY_*`, `PO_TERMS`).

**Freightos (optional external source):**

| Var | Purpose |
|---|---|
| `FREIGHTOS_ENABLED` | master toggle (default `false`) |
| `FREIGHTOS_API_KEY` / `FREIGHTOS_API_SECRET` | developer-app credentials (both required) |
| `FREIGHTOS_AUTH_MODE` | `basic` (default) \| `oauth2` \| `headers` |
| `FREIGHTOS_TOKEN_URL` | OAuth2 token endpoint (⚠️ default is a guess; needs the real URL) |
| `FREIGHTOS_BASE_URL` | `https://api.freightos.com/api/v1` |
| `FREIGHTOS_INDEX_PATH` | `/co2calc` |
| `FREIGHTOS_TIMEOUT_SECONDS` | request timeout |
| `FREIGHTOS_LANES` | comma-separated lanes (legacy rate-feed param) |

**AI advisor (optional LLM narration; Phase 10):**

| Var | Purpose |
|---|---|
| `ADVISOR_LLM_ENABLED` | master toggle (default `false`) |
| `ANTHROPIC_API_KEY` | Claude API key — required for live narration; absent ⇒ deterministic briefing only |
| `ADVISOR_MODEL` | model id (default `claude-opus-4-8`) |
| `ADVISOR_BASE_URL` | Anthropic Messages API URL (default `https://api.anthropic.com/v1/messages`) |
| `ADVISOR_MAX_TOKENS` / `ADVISOR_TIMEOUT_SECONDS` | generation cap / request timeout |

The advisor is inert (no external call, no cost) unless `ADVISOR_LLM_ENABLED=true` **and** `ANTHROPIC_API_KEY` is set; the key is never logged (`ClaudeLLMProvider.__repr__` is redacted).

**External intelligence providers + scheduler (all OPTIONAL, inert by default):**

| Var | Purpose |
|---|---|
| `INTEL_EXCHANGERATE_ENABLED` (+ `INTEL_EXCHANGERATE_API_KEY`) | FX volatility → trade/country signals |
| `INTEL_WORLDBANK_ENABLED` | GDP-growth stress → geopolitical/country signals (keyless) |
| `INTEL_IMF_ENABLED` | inflation → trade/country signals (keyless) |
| `INTEL_GDELT_ENABLED` | disruption-news volume → global geopolitical signal (keyless) |
| `INTEL_OPENWEATHER_ENABLED` + `INTEL_OPENWEATHER_API_KEY` | severe weather at ports → port/country signals (key required) |
| `INTEL_COMTRADE_ENABLED` + `INTEL_COMTRADE_API_KEY` | trade-flow change → trade signals (subscription key) |
| `INTEL_HTTP_TIMEOUT_SECONDS` | per-request timeout for the above |
| `INTEL_SCHEDULER_ENABLED` / `INTEL_SCHEDULER_INTERVAL_HOURS` | daily background pull per tenant (default off / 24h) |

Each provider is off until enabled (OpenWeather/Comtrade also need a key); enabling makes the scheduler/`POST /intelligence/ingest` pull from it. Paid providers (Freightos/Xeneta/Trading Economics) are deliberately **not** wired — they plug into the same registry later.

---

## 10. APIs configured

**Internal REST (prefix `/api/v1`)**

| Area | Endpoints |
|---|---|
| auth | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me` |
| products | CRUD `/products` (now includes Product Intelligence Profile fields) |
| suppliers | CRUD `/suppliers` |
| warehouses | CRUD `/warehouses` |
| inventory | `/inventory` receive/issue/adjust/transfer, list, `/inventory/movements` |
| purchase-orders | create/submit/approve/reject/cancel/send/receive, `/pdf`, `/email`, `/events` |
| reorder | `POST /reorder/run`, `GET /reorder/recommendations`, `POST /reorder/purchase-orders` |
| demand | `POST /demand/rebuild` |
| forecast | `POST /forecast/run` (`method` accepts a provider key or `"auto"`), `POST /forecast/analyze` (measured demand pattern), `GET /forecast`, `/forecast/providers` (incl. `auto`), `/forecast/summary`, `GET /forecast/{id}/accuracy` |
| intelligence | `GET /intelligence/dashboard`, `POST /intelligence/ingest`, `POST`/`GET /intelligence/signals`, `POST /intelligence/impact`, `POST /intelligence/suppliers/refresh`, `GET /intelligence/suppliers`, `GET /intelligence/suppliers/{id}` |
| container | `GET /container/containers` (specs), `POST /container/plan` (load plan + recommendation + MOQ-aware top-off), `POST /container/plan/from-recommendations` (plan straight from reorder recommendation ids) |
| advisor | `GET /advisor/briefing` (deterministic, explainable findings + metrics; optional LLM `narrative`), `POST /advisor/ask` (free-text question → relevant findings now + LLM answer when configured) |
| dashboard / reports | `GET /dashboard/metrics`, `/reports/inventory-aging`, `/reports/supplier-performance` |
| users | CRUD `/users` + `/users/roles` |

**External integrations:** Freightos CO2 API (`POST /api/v1/co2calc`) — configured behind `ExternalSource`, auth pending (§8).

---

## 11. Pending tasks

1. **Freightos auth** — obtain documented auth scheme + token URL; set `FREIGHTOS_AUTH_MODE` (+ token URL); re-probe; confirm credentials.
2. **CO2 adapter rework** — POST + request body + CO2-appropriate normalization (the GET rate-feed shape doesn't fit `/co2calc`).
3. ✅ **Scheduled ingestion — DONE** — `intelligence/scheduler.py` runs daily (config-gated), per tenant, ingesting all enabled providers + refreshing supplier scores (§4). Verified live against World Bank.
4. **Frontend** — built: Intelligence Dashboard, **AI Analyst** (`/advisor`), **Forecasting** (`/forecast`: summary + run + recent + `analyze` demand-pattern view + `auto` method), **Supplier Scorecards** (`/supplier-scores`: grade A–F, risk, reliability/on-time/fill, refresh), and **Container Load Planner** (`/container`: line builder + plan-from-pending-reorders → recommended container, volume/weight utilisation, binding constraint, MOQ top-off). Remaining: product-intelligence-profile fields on the Products screen and reorder risk columns. Frontend typechecks and production-builds clean (`npm run lint` / `npm run build`); **all four new screens are render-verified live** (Vite + browser, demo admin) — Forecasting ran a real forecast (14 generated); Containers planned 5000 cartons → 40GP at 90% volume fill.

---

## 12. Future roadmap

| Phase | Scope |
|---|---|
| ~~7 — Forecast Intelligence~~ | ✅ **DONE** — detection + Croston/seasonal providers + auto selection + `/forecast/analyze` (see §7) |
| **8 — Freight Intelligence** | finish Freightos auth + CO2 adapter; add Xeneta/SeaRates `ExternalSource` adapters; scheduled ingestion |
| ~~9 — Container Optimization~~ | ✅ **DONE** — 20GP/40GP/40HC load planning from carton dims + MOQ (see §2/§10), **including the reorder→container tie-in** (`POST /container/plan/from-recommendations` plans a shipment straight from reorder recommendations). |
| **10 — AI Supply Chain Analyst** | ✅ **built** — deterministic explainable briefing over reorder·signals·suppliers·forecasts·**container**, `GET /advisor/briefing` + `POST /advisor/ask`, with an inert Claude (`claude-opus-4-8`) narrator. Remaining: set `ANTHROPIC_API_KEY` to switch on live narration; add freight findings once Freightos is live. |
| **Hardening (cross-cutting)** | Redis-backed rate limiter; CI pipeline; tenant onboarding; cross-tenant RLS isolation test; set-based bulk loops; multi-currency consolidation |

---

## 13. Known issues

- **Freightos auth unresolved** (§8) — integration inert until fixed; safe (returns nothing).
- **In-memory rate limiter** — single-instance only; needs Redis for multi-instance.
- **No CI pipeline** — tests are run manually; integration tests gated on `DATABASE_URL`.
- **No self-serve tenant onboarding** — tenants created by seed/migration only.
- **Reorder/forecast bulk loops are O(products × warehouses)** — fine for hundreds; move to set-based queries before large catalogs.
- **Reservation/allocation unimplemented** — `qty_reserved`/`qty_damaged` columns exist but no service writes them.
- **PO email + PDF run inside the request transaction** — move to a background worker.
- **Multi-currency not consolidated** in dashboard/report rollups.
- **Country-code normalization — DONE.** `intelligence/domain/geo.py` `to_iso2()` folds free-text / ISO-3 / country names to ISO-2 and is applied on both sides in `build_snapshot`/`match_context`, so a supplier stored as `USA` now matches a `US` signal. Verified live (demo `USA` supplier matched the `US` IMF inflation signal — 0 before, 2 after). The map covers the major economies; unmapped inputs return `None` (no match, as before). The currency/M49/ISO-3 maps in `providers/external.py` remain curated subsets. Provider severity mappings are first-pass and tunable; UN Comtrade aggregates to one signal per reporter country (the raw API is one row per HS commodity — 100k+) with conservative severity (YoY change only) pending a concentration model. **Live-verified (with keys):** World Bank (58), IMF (21), OpenWeather, and Comtrade pull live; a full scheduler cycle persisted 171 signals across 2 tenants. GDELT works but is rate-limited (429 on rapid calls; the daily cadence is fine and it degrades to `[]`). ExchangeRate.host needs a *valid* apilayer access key (the supplied one returned `invalid_access_key`).
- **Cross-tenant RLS isolation — now TESTED.** `tests/integration/test_tenant_isolation.py` logs in as two seeded tenants (demo / globex) and asserts disjoint catalogs + a cross-tenant `GET /products/{id}` → 404, proving RLS holds end-to-end as `app_user`. The demo seed now creates a minimal **second tenant** (`globex`, `admin@globex.com`) for this. The integration `conftest.py` bypasses the in-memory rate limiter (the suite makes many logins in <1 min; the 10/min auth limit would otherwise 429 later tests — the limiter has its own unit tests).
- **Local dev caveat:** Python 3.14 on this host can't compile `asyncpg`/`bcrypt` (no MSVC) — the venv runs pure-domain/service unit tests; app boot + integration + the `test_rbac` collection run in **Docker** (see the corrected test command in §How to run — the runtime image deliberately omits test tooling).
- **Runtime image has no test deps:** `backend/Dockerfile` installs only `requirements.txt`; `pytest`/`pytest-asyncio`/`httpx` live in `requirements-dev.txt`. So `docker compose run --rm api pytest` fails (`pytest: not found`). Run tests by mounting the source and installing dev deps (§How to run), or add a dev build stage / CI image.
- **Integration test harness — FIXED (was an event-loop bug):** the module-level async `engine` (`app/db/session.py`) binds its asyncpg connections to the loop they're created on, but `pytest-asyncio` (auto mode) runs each test on a fresh loop, so a pooled connection reused by a later test raised `RuntimeError: ... attached to a different loop`. Resolved by `tests/integration/conftest.py`, which disposes the engine pool after each test (autouse). With the harness fixed, two **pre-existing product bugs** it had masked were also fixed: (1) PO generation now consolidates duplicate recommendations for the same product into one line (`reorder/service.py` — the `(po_id, product_id)` unique constraint otherwise 500'd when several pending recs targeted one product); (2) the error handlers now `jsonable_encoder` their payloads (`core/exceptions.py`), so validation of a `Decimal`-bounded field — e.g. `service_level` — returns 422 instead of crashing on `json.dumps`. Integration suite is now green (11/11, incl. the new RLS isolation test).

---

## 14. Next recommended actions

1. **Unblock Freightos:** get the documented auth scheme + OAuth2 token URL → set `FREIGHTOS_AUTH_MODE`/`FREIGHTOS_TOKEN_URL` → re-probe → confirm credentials. Then rework the adapter for `POST /co2calc` (CO2 semantics).
2. **Add a CI pipeline** (ruff + unit on push; integration against an ephemeral Postgres) — biggest production-readiness gap and protects everything above.
3. ✅ **Cross-tenant RLS isolation test — DONE** (§13); the multi-tenant security cornerstone is now proven in CI-ready form.
4. **Phase 10 (AI Supply Chain Analyst)** — ✅ **built** (deterministic explainable briefing + `GET /advisor/briefing` + `POST /advisor/ask`, container findings folded in, inert Claude narrator). To switch on live narration: set `ADVISOR_LLM_ENABLED=true` + `ANTHROPIC_API_KEY` (§9). Remaining: freight findings once Freightos is live.
5. **CI pipeline** — now genuinely viable (suite green, harness fixed). Blocked only on a git remote: the repo isn't yet under git, so a GitHub Actions workflow can't be verified here. Mirror the §How-to-run Docker commands (ruff + `pytest tests/unit`; integration against an ephemeral Postgres provisioned by the 12 init scripts).
5. **Schedule supplier-score refresh** — a small scheduler that runs `refresh_supplier_scores` keeps scores current without a UI action and is valuable even before external feeds are live.

---

### How to run (reference)
```bash
# Full stack (fresh init runs 12 ordered SQL scripts: 10 schema migrations + app_user role + demo seed)
docker compose down -v && docker compose up --build
#   API:    http://localhost:8000/docs        Health: /health
# Frontend
cd frontend && npm install && npm run dev      # http://localhost:5173
# Tests in Docker (the runtime image has NO test deps, so mount source + install dev deps).
# asyncpg paths (test_rbac) need this; pure-domain tests also run in a local venv.
docker compose run --rm --user root -v "$PWD/backend:/src" -w /src --entrypoint sh api \
  -c "pip install -q -r requirements-dev.txt && python -m pytest tests/unit tests/integration -q"
#   green: 344 unit + 11 integration = 355 (integration needs a fresh DB: docker compose down -v first).
# Boot smoke-check (no test deps needed):
docker compose run --rm api python -c "import app.main as m; print(sorted(r.path for r in m.app.routes))"
# Login (demo seed, two tenants): admin@demo.com / ChangeMe123!  ·  admin@globex.com / ChangeMe123!
```
