# Reorder & Procurement Engine

The reorder engine is the platform's core IP. It is implemented as an
**independent domain module** — a pure Python package with **no framework or
database imports** — wrapped by thin adapters (schemas, repository, service,
API). The calculation core can be imported and tested with zero infrastructure.

```
app/reorder/
├── domain/                 # PURE core (stdlib only) — the intellectual property
│   ├── models.py           # DemandStatistics, StockPosition, ReorderPolicy, ReorderResult, ...
│   ├── rounding.py         # full-carton rounding + MOQ enforcement
│   ├── safety_stock.py     # days-cover and statistical safety stock
│   ├── engine.py           # compute_reorder(...) — orchestrates the formulas
│   └── exceptions.py
├── schemas.py              # Pydantic request/response models
├── repository.py           # async DB access (demand, stock, on-order, recs, POs)
├── service.py              # orchestration + persistence + auditing
└── api.py                  # FastAPI routers

app/models/procurement.py   # ORM mapping for the procurement tables
examples_reorder.py         # runnable, dependency-free worked scenarios
```

Run the worked scenarios with no dependencies installed:

```bash
cd backend
PYTHONPATH=. python examples_reorder.py
```

## Formulas

For each `(product, warehouse)`:

```
average_daily_demand (ADD) = total units sold in window / window length (days)
average_monthly_sales      = ADD x 30

safety_stock (SS):
    days_cover  : SS = ADD x safety_days
    statistical : SS = z(service_level) x sigma_daily x sqrt(lead_time_days)
    (a manual products.safety_stock override always wins)

reorder_point (ROP)   = ADD x lead_time_days + SS
    (a manual products.reorder_point override always wins)

order_up_to_level (S) = ADD x (lead_time_days + review_period_days) + SS
    (clamped so S >= ROP)

inventory_position(IP)= available_stock + on_order
                        available_stock = on_hand - reserved - damaged

reorder when          IP <= ROP
raw_order_qty         = max(0, S - IP)
final order quantity  = full-carton rounding, then MOQ enforcement
```

Demand standard deviation is computed from SQL aggregates over a **zero-filled**
daily series: with `N` = window length in calendar days, `mean = Σqty / N` and
`variance = Σqty² / N − mean²`. Days with no sales contribute nothing to either
sum but still count toward `N`, so no row is needed for zero-sales days.

`z(service_level)` is the inverse standard-normal CDF; e.g. 0.95 → 1.6449,
0.975 → 1.96, 0.99 → 2.3263.

## The two business rules

**Full carton rule** — never order partial cartons; round the quantity UP to a
whole multiple of `units_per_carton`.

**MOQ rule** — never order below the minimum order quantity; if the cartoned
quantity is below MOQ, raise it to the MOQ (itself rounded up to whole cartons,
so the full-carton rule is never broken). MOQ is only enforced once an order is
actually warranted (a non-positive raw quantity orders nothing).

| units_per_carton | MOQ | calculated | final | note |
|---|---|---|---|---|
| 10 | 0 | 67 | **70** | rounded up to 7 cartons |
| 1 | 500 | 320 | **500** | raised to MOQ |
| 10 | 500 | 505 | **510** | rounds to 51 cartons; MOQ already met |
| 12 | 500 | 10 | **504** | MOQ 500 rounded up to whole cartons (42 × 12) |

## Worked scenarios

All figures below are produced by `compute_reorder(...)` and are locked in by
`tests/unit/test_reorder_domain.py`.

**1 — Healthy stock (no order).** ADD 5, lead 10, safety 7 days →
SS 35, ROP 85. On hand 200 ⇒ IP 200 > 85 ⇒ no order.

**2 — Below reorder point (order to target).** ADD 5, lead 10, review 14,
safety 7 → SS 35, ROP 85, S 155. On hand 40 ⇒ gap 115 ⇒ round up (UPC 12) to
**120 units (10 cartons)**.

**3 — MOQ-binding.** ADD 2, lead 7, safety 5 → ROP 24. On hand 5, UPC 10,
MOQ 500 ⇒ raw 19 → cartoned 20 → **500 units (50 cartons)**, `applied_moq=true`.

**4 — Carton-binding.** ADD 3.3, lead 10, safety 7 → ROP 56.1. On hand 20,
UPC 24 ⇒ gap 36.1 → **48 units (2 cartons)**.

**5 — Statistical safety stock.** Demand sample `[10,12,8,11,9,10,13,7,10,10]`
(total 100, Σqty² 1028, window 10) → ADD 10, σ/day 1.6733. Lead 9,
service 0.95 (z 1.6449) → SS 8.2573, ROP 98.2573. On hand 50, UPC 6 ⇒ gap
48.2573 → **54 units (9 cartons)**.

**6 — Zero demand, zero stock.** ADD 0 → ROP 0, S 0. IP 0 ≤ 0 triggers, but the
order-up-to gap is 0 ⇒ **no order**.

**7 — On-order suppresses reorder.** ADD 5 → ROP 85. On hand 40 with 100 on
order ⇒ IP 140 > 85 ⇒ **no order** (inbound stock already covers the need).

**8 — Reserved stock reduces availability.** On hand 100 with 80 reserved ⇒
available 20. ADD 5, review 7 → ROP 85, S 120 ⇒ gap 100 → **108 units
(9 cartons)** despite the high on-hand figure.

**9 — Manual reorder-point override.** Override ROP 50 (formula would give 85).
On hand 60 ⇒ IP 60 > 50 ⇒ **no order**.

## API

Mounted under `/api/v1` (JWT required; permissions from the RBAC seed).

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/reorder/run` | `reorder.run` | Evaluate reorder needs; optionally persist actionable recommendations |
| GET | `/reorder/recommendations` | `reorder.read` | List persisted recommendations (filter by status/warehouse/supplier) |
| POST | `/purchase-orders` | `po.create` | Generate draft POs from selected recommendations |
| GET | `/purchase-orders` | `po.read` | List purchase orders |
| GET | `/purchase-orders/{id}` | `po.read` | Get a purchase order with its lines |

`POST /reorder/run` body (all optional): `warehouse_id`, `category_id`,
`supplier_id`, `window_days` (default 90), `review_period_days` (0),
`safety_days` (7), `service_level` (0.95), `method` (`days_cover` |
`statistical`), `only_below_rop` (true), `persist` (true).

`POST /purchase-orders` body: `recommendation_ids` (required), `notes`,
`expected_date`. Recommendations are grouped into one PO per
`(supplier, warehouse)`; line cost is the supplier-specific cost if present,
otherwise the product cost; the PO is created as `draft` and each converted
recommendation is marked `ordered`. Recommendations without a supplier, or not
in a `pending`/`accepted` state, are skipped and reported in
`skipped_recommendation_ids`. PO numbers come from the database
`next_po_number(tenant)` function (`PO-YYYY-00001`).

### Effective ordering terms

The service resolves each product's policy as: supplier = `primary_supplier_id`;
`units_per_carton`, `moq`, `lead_time_days`, and `cost` taken from the matching
`supplier_products` row when present, otherwise from the product; reorder-point
and safety-stock overrides from the product. The pure engine receives only
numbers — it has no knowledge of suppliers or the database.

## Persistence

These tables are **already provisioned by the database layer**
(`database/sql/schema.sql`, sections 6 “Demand” and 7 “Procurement”) and are
under tenant Row-Level Security. This module maps ORM models onto them
(`app/models/procurement.py`); it does **not** create a new migration.

- `sales_daily(product_id, warehouse_id, sale_date, qty_sold)` — demand source.
- `reorder_recommendations` — persisted actionable recommendations
  (`available_qty`, `on_order_qty`, `avg_daily_demand`, `reorder_point`,
  `safety_stock`, `recommended_qty`, `recommended_cartons`, `supplier_id`,
  `status`). Richer run-time fields (order-up-to level, monthly demand, method,
  reason) are returned live by `POST /reorder/run` but not stored.
- `purchase_orders` / `purchase_order_lines` — generated POs and their lines.
- `po_counters` + `next_po_number(tenant)` — concurrency-safe PO numbering.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest                          # unit tests (no DB)
DATABASE_URL=postgresql+asyncpg://app_user:app_pw@localhost:5432/inventory \
JWT_SECRET_KEY=dev pytest tests/integration   # full API + DB
```

- `tests/unit/test_reorder_rounding.py` — the full-carton and MOQ rules, incl.
  the two documented examples and edge cases.
- `tests/unit/test_reorder_domain.py` — the engine across all nine scenarios.
- `tests/unit/test_reorder_service.py` — orchestration with fakes: recommendation
  persistence + auditing, PO grouping/numbering/totals, supplier splitting, and
  skip handling.
- `tests/integration/test_reorder_api.py` — login → run → list → generate PO
  against a live database (auto-skipped when `DATABASE_URL` is unset).
