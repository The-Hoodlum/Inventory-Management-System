# Production deployment

This is the runbook for hosting the Inventory & Procurement Platform on a server. It uses
`docker-compose.prod.yml`, which differs from the local/eval stack in the ways that matter
for production:

- **Clean database** — schema + RBAC + every feature module, then **one** tenant/admin
  from your environment. No demo business data.
- **Secrets from the environment** — nothing sensitive is defaulted; the stack refuses to
  start until you provide them.
- **Database is not exposed** — only the web tier is reachable; the API and DB sit on the
  internal Docker network.
- **One origin** — nginx serves the built frontend and reverse-proxies `/api` to the
  backend, so the browser talks to a single host (no CORS surface, no open API port).

```
        browser ──▶ web (nginx :80)  ──/api──▶ api (FastAPI :8000) ──▶ db (Postgres, internal)
                     └ serves the SPA
```

---

## 1. Prerequisites

- A Linux host (a small VPS is fine: 2 vCPU / 2–4 GB RAM to start) with **Docker Engine +
  Docker Compose v2**.
- The repository checked out on that host.
- Optional but recommended: a domain name pointed at the host, for TLS (see §5).

---

## 2. Configure

```bash
cp .env.prod.example .env.prod
```

Edit `.env.prod` and set at least these. Generate real secrets — do not hand-pick them:

```bash
openssl rand -hex 32      # -> JWT_SECRET_KEY
openssl rand -base64 24   # -> POSTGRES_PASSWORD
```

| Variable | What it is |
|---|---|
| `POSTGRES_PASSWORD` | Postgres superuser password (internal only). |
| `JWT_SECRET_KEY` | 32+ char random string. Rotating it logs everyone out. |
| `CORS_ORIGINS` | Your public site URL, e.g. `https://erp.yourcompany.com`. |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | The first administrator, created on first boot. |
| `TENANT_NAME` / `TENANT_SLUG` | Your company name + a short unique id. |

`.env.prod` holds secrets — it is already covered by `.gitignore` patterns; never commit it.

---

## 3. Launch

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

First boot provisions the database once (schema → RBAC → all modules → your admin). Watch
it come up:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api
```

Verify:
- API health (from the host): `curl -s localhost:8000/health` is not exposed publicly;
  instead check the container is healthy in `ps`, or `curl -s localhost/api/v1/../health`
  via the web tier.
- Open `http://<host>/` (or your domain) and **log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`**.

**Immediately change the admin password** from the app after first login.

---

## 4. Load your real data

The database starts empty of business data. Load your catalog, stock, and bikes through the
in-app **Import** flows (Products, Inventory opening balances, Motorcycle import), or the
reconstruction importers (opening balances → replay → reconcile) — the same path used for
the Lusaka load. Everything goes through the normal validated, audited import framework; no
direct SQL writes.

---

## 5. Put it behind TLS

The web tier listens on plain HTTP (`WEB_PORT`, default 80). Terminate TLS in front of it —
pick one:

- **Caddy** (simplest automatic HTTPS). Point Caddy at `web:80` (or the host port) with your
  domain; it fetches and renews Let's Encrypt certificates automatically.
- **Cloudflare Tunnel** — no open inbound ports; run `cloudflared` alongside the stack.
- **nginx + certbot** on the host, proxying to the web container.

Set `CORS_ORIGINS` (and your DNS) to the HTTPS URL. Keep the DB and API ports unpublished.

---

## 6. Backups

The data lives in the `pgdata` Docker volume. Take regular logical backups:

```bash
# nightly dump (add to cron)
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  pg_dump -U postgres inventory | gzip > backup-$(date +%F).sql.gz

# restore into a fresh, EMPTY database
gunzip -c backup-YYYY-MM-DD.sql.gz | \
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db psql -U postgres inventory
```

Store copies off the host.

---

## 7. Upgrades (new code / schema)

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

The first-boot SQL runs **only** on an empty database, so a code update alone does **not**
change an existing schema. When a release adds a database module (a new
`database/sql/<name>.sql`), apply it to the running DB — the module files are idempotent:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec db \
  psql -U postgres -d inventory -f /sql/<name>.sql
```

For example, the finance module (cash book / treasury) ships four modules — apply them in
this order, since the later ones reference `financial_accounts`:

```bash
for m in finance_accounts finance_payment_mapping finance_expenses finance_transfers_handovers; do
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec db \
    psql -v ON_ERROR_STOP=1 -U postgres -d inventory -f "/sql/$m.sql"
done
```

This is the same schema the authoritative `alembic upgrade head` path produces (CI proves
the two stay equivalent). If you prefer Alembic, run it from the repo against the DB with
the backend dependencies available; see `.github/workflows/ci.yml` (the "Alembic upgrade"
job) for the exact invocation.

---

## 8. Optional: WhatsApp channel

Staff can query the system from WhatsApp and receive critical alerts. It needs the public
HTTPS URL from §5, so set it up after the site is live. Full step-by-step (Meta app, tokens,
webhook, linking staff numbers, the 24-hour window): **[WHATSAPP.md](WHATSAPP.md)**.

It stays completely inert until `WHATSAPP_PROVIDER=cloud` **and** credentials are supplied —
the adapter falls back to a mock that records messages instead of sending them.

---

## 9. Hardening checklist

- [ ] Change the admin password after first login (and use per-person accounts, not shared).
- [ ] Rotate the internal `app_user` DB password: change it in `backend/docker/02_app_role.sql`
      **and** the `DATABASE_URL` in `.env.prod`, then recreate the DB volume (fresh install)
      or `ALTER ROLE app_user PASSWORD '…'` on an existing one.
- [ ] Keep `POSTGRES_PASSWORD` / `JWT_SECRET_KEY` in a secret manager, not in shell history.
- [ ] Firewall the host so only 80/443 are public; the DB (5432) and API (8000) stay internal.
- [ ] Set up the nightly backup (§6) and test a restore at least once.

## Known limitations (see also the roadmap)

- **No self-service signup** — the first admin is created by this bootstrap; additional
  users are created in-app by an admin. Multi-tenant onboarding is a future item.
- **Rate limiting is in-memory** — fine for a single API container; needs Redis before
  scaling to multiple API instances.
