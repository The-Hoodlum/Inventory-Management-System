# Purchase Order Management & Goods Receiving

A production-grade vertical module that completes the procurement cycle: purchase
order authoring, the full approval workflow, sending to suppliers, and goods
receiving with transactional inventory integration. It mirrors the reorder
engine's architecture — a **pure domain core** (no framework or I/O imports)
wrapped by adapters (schemas, repository, service, API).

---

## 1. Folder structure

```
app/procurement/
├── __init__.py
├── domain/                  # pure, stdlib-only, unit-tested in isolation
│   ├── __init__.py
│   ├── exceptions.py        # ProcurementDomainError, InvalidTransitionError, ReceiptError
│   ├── states.py            # POStatus, POAction, transition rules, can_edit/is_terminal
│   └── receiving.py         # apply_receipt(): full/partial/multiple, over-receipt guard
├── schemas.py               # request/response models (Pydantic v2)
├── repository.py            # async data access (PO header, lines, events) + row locking
├── service.py               # ProcurementService — orchestration (the use cases)
├── pdf.py                   # build_purchase_order_pdf() -> bytes (fpdf2)
├── email.py                 # EmailService — SMTP send / approval / receipt notices
└── api.py                   # FastAPI routes (mounted at /api/v1/purchase-orders)

app/models/procurement.py    # + PurchaseOrderEvent ORM model
examples_procurement.py      # runnable demo of the state machine + receiving (no DB)
tests/unit/test_po_state_machine.py
tests/unit/test_po_receiving_domain.py
tests/unit/test_procurement_service.py     # workflow / approval / receiving (fakes, no DB)
tests/integration/test_procurement_api.py  # full lifecycle vs a live DB (skipped without one)
```

---

## 2. Database changes

One **additive, idempotent** table — `purchase_order_events` — an append-only
lifecycle timeline that complements the generic `audit_logs` with a queryable,
PO-specific history (including approval/rejection comments and receipt details).

| column | type | notes |
|---|---|---|
| id | uuid | PK |
| tenant_id | uuid | FK → tenants, RLS scope |
| po_id | uuid | FK → purchase_orders (CASCADE) |
| action | text | created / updated / submitted / approved / rejected / cancelled / sent / received / closed / emailed |
| from_status / to_status | text | status transition |
| comment | text | approval / rejection / receipt note |
| detail | jsonb | structured payload (e.g. received quantities) |
| actor_id | uuid | FK → users (SET NULL) |
| created_at | timestamptz | default now() |

Delivered three ways so no environment drifts:
- **`database/sql/po_events.sql`** — idempotent DDL (CREATE TABLE IF NOT EXISTS,
  guarded RLS policy + grant). Mounted by docker-compose as `05_po_events.sql`.
- **Alembic migration `0003_po_events`** — runs the same file (`alembic upgrade head`).
- RLS is enabled + forced with the same `app.current_tenant` policy as every
  other business table.

The existing `purchase_orders` / `purchase_order_lines` tables already satisfy
the PO header and line requirements (status CHECK, `received_qty`, the
`next_po_number()` sequence function), so no changes were needed there.

> Note on status naming: the fully-received state is stored as **`received`**
> (matching the existing DB CHECK constraint), which this module treats as
> "Fully Received".

---

## 3. State machine

```
 draft ──submit──▶ pending_approval ──approve──▶ approved ──send──▶ sent
   │                    │                           │                │
 cancel            reject │ cancel               cancel           receive
   ▼                  ▼   ▼                          ▼          (qty-driven)
cancelled    rejected   cancelled              cancelled    partially_received
                                                                  │      │
                                                             receive   receive
                                                                  ▼      ▼
                                                  partially_received    received
```

- **Editing** (header/lines) is allowed **only** while `draft`.
- **Receiving** is allowed only from `sent` or `partially_received`; the
  resulting status (`partially_received` vs `received`) is computed from the
  cumulative received quantities, never set directly.
- **Terminal** states: `received`, `cancelled`, `rejected`.
- Invalid transitions raise `InvalidTransitionError` → surfaced as **HTTP 409**.

All transition rules are verified by `tests/unit/test_po_state_machine.py`
(7 valid + 22 invalid cases).

---

## 4. API

Base path: **`/api/v1/purchase-orders`**

| Method & path | Purpose | Permission |
|---|---|---|
| `POST   /` | Create a draft PO (header + lines) | `po.create` |
| `GET    /` | List POs (filter by status/supplier/warehouse, paginated) | `po.read` |
| `GET    /{id}` | Get one PO with lines | `po.read` |
| `PATCH  /{id}` | Edit a draft PO (replace fields / lines) | `po.update` |
| `POST   /{id}/submit` | Submit for approval | `po.create` |
| `POST   /{id}/approve` | Approve (stores approver + timestamp + comment) | `po.approve` |
| `POST   /{id}/reject` | Reject (stores comment) | `po.approve` |
| `POST   /{id}/cancel` | Cancel | `po.update` |
| `POST   /{id}/send` | Mark sent to supplier | `po.approve` |
| `POST   /{id}/receipts` | Receive goods (full / partial / repeat) | `inventory.receive` |
| `GET    /{id}/events` | Lifecycle timeline | `po.read` |
| `GET    /{id}/pdf` | Professional PO PDF (`application/pdf`) | `po.read` |
| `POST   /{id}/email` | Email the PO (PDF attached) to the supplier | `po.approve` |

The approval-action endpoints accept an optional `{ "comment": "..." }` body.

### RBAC mapping rationale
The module **reuses the existing seeded permissions** (no seed churn). Receiving
maps to `inventory.receive` because it is the same capability that creates stock
— a receipt writes the inventory ledger. The Procurement system role
(`po.create/update/approve`) can drive a PO from creation through send; an
Inventory/Warehouse role (holding `inventory.receive`) performs the physical
receipt. Admin holds every permission.

---

## 5. Reorder-engine integration

The reorder engine produces recommendations and can still generate **draft POs**
from them — that endpoint now lives at **`POST /api/v1/reorder/purchase-orders`**
(generation only). Everything after the draft — review (`GET`), edit (`PATCH`),
submit, approve, send, receive — is owned by this module. The flow:

```
Low stock → reorder recommendation → carton rounding → MOQ enforcement
          → draft purchase order  →  [this module]  → review / edit / approve
          → send → receive goods → inventory updated
```

`/api/v1/purchase-orders` is the single canonical surface for the PO lifecycle.

---

## 6. Goods receiving & inventory integration

A receipt is **one atomic transaction** (the request transaction). For each
received line it:

1. writes a `stock_movements` row (`movement_type='receipt'`,
   `reference_type='purchase_order'`, `reference_id=po.id`, `unit_cost`),
2. increments warehouse `inventory.qty_on_hand` (available stock is the
   DB-generated `qty_on_hand − reserved − damaged`, so it follows automatically),
3. updates the line's `received_qty` (PO balance),
4. recomputes and sets the PO status (`partially_received` / `received`),
5. appends a `purchase_order_events` row (with received quantities) and an
   `audit_logs` row; on full receipt it also records `closed` / `po.closed`.

If any step fails, the whole receipt rolls back. The PO row and its lines are
locked with `SELECT ... FOR UPDATE` so concurrent receipts cannot race.

---

## 7. PDF & email

- **PDF** (`pdf.py`, fpdf2 — pure Python): company block, supplier block, PO meta,
  line-item table (item, qty, units/carton, cartons, unit cost, line total),
  totals, notes, terms & conditions, and three signature areas (Prepared /
  Approved / Received). Company identity and default terms come from settings
  (`COMPANY_NAME`, `COMPANY_ADDRESS`, `COMPANY_EMAIL`, `COMPANY_PHONE`, `PO_TERMS`).
- **Email** (`email.py`, stdlib `smtplib`): runs the blocking send on a worker
  thread; **degrades gracefully** — when `SMTP_ENABLED` is false (the default),
  sends are skipped and logged rather than failing the request. Configure via
  `SMTP_HOST/PORT/USERNAME/PASSWORD/USE_TLS/FROM`.

---

## 8. Audit

Every action writes an `audit_logs` entry: `po.create`, `po.update`,
`po.submitted`, `po.approved`, `po.rejected`, `po.cancelled`, `po.sent`,
`goods.received`, `po.closed`, `po.emailed` — plus the richer
`purchase_order_events` timeline described above.

---

## 9. Testing

| File | Scope | DB needed |
|---|---|---|
| `tests/unit/test_po_state_machine.py` | All valid + invalid transitions, edit/terminal guards | no |
| `tests/unit/test_po_receiving_domain.py` | Receipt math: full / partial / multiple / over / zero / unknown | no |
| `tests/unit/test_procurement_service.py` | Workflow, approval, receiving, inventory effects, audit/events (fakes) | no |
| `tests/integration/test_procurement_api.py` | Full lifecycle + receiving + events + PDF over the real app | yes (`DATABASE_URL`) |

Run unit tests (hermetic):

```bash
cd backend
pip install -r requirements-dev.txt
pytest tests/unit -q
```

Run everything including the live API flow:

```bash
export DATABASE_URL=postgresql+asyncpg://app_user:app_pw@localhost:5432/inventory
export JWT_SECRET_KEY=dev-secret
pytest -q
```

The pure domain can also be demonstrated with **no dependencies at all**:

```bash
python examples_procurement.py
```
