# WhatsApp integration

Step-by-step setup for the WhatsApp channel: your staff ask the system questions in
WhatsApp ("how many CG125 in Lusaka?", "what did we sell today?") and get answers scoped to
their own permissions, plus opt-in push of critical alerts.

Read [DEPLOYMENT.md](DEPLOYMENT.md) first — WhatsApp needs a **publicly reachable HTTPS
URL**, so the platform must already be deployed and on a domain.

---

## What you get

| Direction | What it does | Requires |
|---|---|---|
| **Inbound** (staff → system) | Natural-language questions answered by the assistant, scoped to the asker's role/branch. | Meta Cloud API **+** `ASSISTANT_ENABLED` + `OPENAI_API_KEY` |
| **Outbound** (system → staff) | Push of `critical` notifications (per-user opt-in). | Meta Cloud API only |

The AI **never touches the database directly** — it calls the same permission-checked tools
the API uses. A user who can't see Solwezi in the app can't see it over WhatsApp either.

### How a message flows

```
WhatsApp ──▶ Meta Cloud API ──▶ POST /api/v1/whatsapp/webhook
                                     │
                     phone → whatsapp_identities → platform user (their permissions)
                                     │
                              AssistantService (OpenAI function-calling → tools)
                                     │
                          reply ──▶ CloudWhatsAppAdapter ──▶ Meta ──▶ WhatsApp
```

---

## Before you start

1. The platform deployed and reachable at `https://your-domain` (TLS terminated — Meta
   **will not** call a plain-HTTP or self-signed endpoint).
2. A **Meta (Facebook) Business account**.
3. A phone number for WhatsApp Business that is **not** already registered on the WhatsApp
   consumer or Business app. (Meta gives you a free **test number** to start — use it.)
4. An **OpenAI API key** — only for inbound Q&A. Outbound alerts work without it.

> **Cost note:** Meta bills business-initiated conversations. Staff-initiated replies inside
> the 24-hour window are free at low volume. Check current Meta pricing for your country.

---

## Step 1 — Create the Meta app and add WhatsApp

1. Go to <https://developers.facebook.com/apps> → **Create app**.
2. Pick use case **Other** → type **Business** → name it (e.g. "Zamoto ERP") and link your
   Business account.
3. On the app dashboard, find **WhatsApp** → **Set up**.
4. Open **WhatsApp → API Setup**. You now have a sandbox with a **test number**.

## Step 2 — Collect the four credentials

Still on **WhatsApp → API Setup**, copy:

| Value on the page | Goes into |
|---|---|
| **Phone number ID** (under "From") | `WHATSAPP_PHONE_NUMBER_ID` |
| **WhatsApp Business Account ID** | `WHATSAPP_BUSINESS_ACCOUNT_ID` |
| **Temporary access token** | `WHATSAPP_ACCESS_TOKEN` (see the warning below) |

Also grab the **App Secret** — **Settings → Basic → App secret → Show** — into
`WHATSAPP_APP_SECRET`. This is what authenticates inbound webhooks; without it the endpoint
accepts any payload that reaches the URL (see [Webhook authentication](#webhook-authentication)).

⚠️ **The temporary token expires in 24 hours.** Fine for testing, useless in production.
For a permanent token:

1. **Business Settings → Users → System users → Add** — create one, role **Admin**.
2. **Add assets** → your WhatsApp app + WhatsApp Account → grant **Full control**.
3. **Generate new token** → select your app → scopes **`whatsapp_business_messaging`** and
   **`whatsapp_business_management`** → set expiry **Never**.
4. Copy it once and store it in your secret manager — Meta won't show it again.

Then invent your own webhook verify token (any random string — you choose it, Meta just
echoes it back):

```bash
openssl rand -hex 16      # -> WHATSAPP_VERIFY_TOKEN
```

## Step 3 — Get your tenant id

Inbound messages must be attributed to a tenant. **Without this the webhook is accepted but
never answered** (you'll see `whatsapp_unrouted` in the logs).

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec db \
  psql -U postgres -d inventory -tAc "SELECT id, name FROM tenants;"
```

## Step 4 — Configure and restart

Edit `.env.prod`:

```bash
# Turn the channel on
WHATSAPP_PROVIDER=cloud
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_BUSINESS_ACCOUNT_ID=123456789012345
WHATSAPP_ACCESS_TOKEN=EAAG...your-permanent-token
WHATSAPP_VERIFY_TOKEN=the-random-string-you-generated
WHATSAPP_APP_SECRET=your-meta-app-secret                          # authenticates webhooks
WHATSAPP_DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000000   # from Step 3

# Needed only for inbound Q&A (outbound alerts work without it)
ASSISTANT_ENABLED=true
OPENAI_API_KEY=sk-...
```

Apply:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d api
```

Confirm the cloud adapter is actually selected (not the mock):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api \
  python -c "from app.core.config import settings; \
print('provider:', settings.whatsapp_provider, '| cloud ready:', settings.whatsapp_cloud_configured)"
# expect ->  provider: cloud | cloud ready: True
```

If it prints `cloud ready: False`, the phone-number id or token is missing — the app
silently falls back to the mock adapter and nothing is ever sent.

## Step 5 — Point Meta's webhook at your server

1. **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL:** `https://your-domain/api/v1/whatsapp/webhook`
3. **Verify token:** exactly the `WHATSAPP_VERIFY_TOKEN` from Step 4.
4. **Verify and save.** Meta immediately sends a `GET` handshake — it must return the
   challenge. Failure here is almost always a wrong verify token, a non-public URL, or a
   TLS problem.
5. Under **Webhook fields**, **Subscribe** to **`messages`**. *(Nothing arrives without
   this — the most commonly missed step.)*

Check the handshake landed:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs api | grep -i whatsapp
```

## Step 6 — Link staff phone numbers to platform users

This is what lets the assistant know **who** is asking (and therefore what they may see).
It also drives outbound push. An unlinked number gets a polite refusal, not data.

Numbers are stored in **E.164 without `+`** — e.g. Zambian `+260 97 1234567` → `260971234567`.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec db psql -U postgres -d inventory
```

```sql
-- Link one staff member (repeat per person)
INSERT INTO whatsapp_identities (tenant_id, phone, user_id)
SELECT t.id, '260971234567', u.id
FROM tenants t, users u
WHERE u.email = 'grace@yourcompany.com'
ON CONFLICT (phone) DO UPDATE SET user_id = EXCLUDED.user_id;

-- Check who is linked
SELECT w.phone, u.email, u.full_name
FROM whatsapp_identities w JOIN users u ON u.id = w.user_id;
```

## Step 7 — Test it

**Inbound:** from a linked phone, message your WhatsApp number. With the test number you
must first add your phone under **API Setup → "To"** (sandbox only accepts listed
recipients).

```
You:  how much stock of CG125 do we have?
Bot:  CG125 — Lusaka: 14 available, Solwezi: 3 available …
```

**Outbound:** trigger a `critical` notification (or use the mock first by setting
`WHATSAPP_PROVIDER=mock` and reading `whatsapp_mock_send` in the logs). Per-user opt-out
lives in the app under notification preferences (`whatsapp_push`).

---

## The 24-hour window (important)

Meta only allows **free-form** messages within **24 hours** of that person's last message to
you. This adapter sends free-form text (`type: "text"`), so:

- ✅ **Replies to staff questions** — always fine, the window is open by definition.
- ⚠️ **Proactive alerts** — delivered only if that person messaged you in the last 24 h.
  Outside the window Meta rejects the send. It is **best-effort**: the failure is logged
  (`whatsapp_cloud_send_failed`) and never breaks the business operation that triggered it.

**Practical workaround:** ask staff to send any message (e.g. "hi") at the start of their
shift, which opens the window for the day.

**Proper fix (not yet implemented):** send an **approved message template** for
business-initiated alerts. Create templates under **WhatsApp → Message templates** (approval
takes minutes to a day), then extend `CloudWhatsAppAdapter.send` to post a `type: "template"`
payload for pushes. Track this before relying on alerts reaching people who haven't messaged
in.

---

## Going live (off the test number)

1. **WhatsApp → API Setup → Add phone number** — add and verify your real business number.
2. Complete **Business Verification** in Business Settings (Meta requires it for production
   messaging volume).
3. Swap `WHATSAPP_PHONE_NUMBER_ID` to the new number's id and restart `api`.
4. Remove the sandbox recipient allow-list restriction (it no longer applies once live).

---

## Webhook authentication

The webhook carries no bearer token (Meta calls it), so inbound payloads are authenticated
by **HMAC-SHA256 over the raw request body**, compared in constant time against Meta's
`X-Hub-Signature-256` header. This is what stops someone who learns the URL from posting a
crafted payload and making the bot reply to a number of their choosing.

**Set `WHATSAPP_APP_SECRET`** (Step 2) to enable it. Behaviour:

| `WHATSAPP_APP_SECRET` | Inbound webhook |
|---|---|
| Set (production) | Verified. Bad/missing/replayed-over-tampered-body signature → **403**, nothing processed. |
| Unset | Verification **disabled** — any payload reaching the URL is processed. Local/mock only. |

Verify it's on after deploying:

```bash
# No signature -> must be 403 once WHATSAPP_APP_SECRET is set
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://your-domain/api/v1/whatsapp/webhook \
  -H 'Content-Type: application/json' -d '{"entry":[]}'
```

Remaining hardening:

- [ ] Keep `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` and the access token in a secret
      manager — never in shell history or git.
- [ ] Optionally also restrict the path at your reverse proxy to
      [Meta's published IP ranges](https://developers.facebook.com/docs/graph-api/webhooks/getting-started)
      (defence in depth; the HMAC is the real control).
- [ ] Rotating the app secret in Meta invalidates in-flight webhooks — update `.env.prod`
      and restart `api` in the same change window.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Webhook verify fails in Meta | Verify token mismatch, URL not public HTTPS | Match `WHATSAPP_VERIFY_TOKEN` exactly; test `curl https://your-domain/api/v1/whatsapp/webhook` from outside |
| Messages arrive, no reply; logs show `whatsapp_unrouted` | `WHATSAPP_DEFAULT_TENANT_ID` not set | Set it (Step 3) and restart `api` |
| Nothing arrives at all | Not subscribed to the `messages` field | Webhook → Webhook fields → Subscribe to `messages` |
| Replies never send | Mock adapter still active | Check Step 4's `cloud ready: True` |
| "I don't know who you are" style refusal | Phone not in `whatsapp_identities`, or wrong format | Link it; store E.164 **without** `+` |
| Assistant replies it's unavailable | `ASSISTANT_ENABLED=false` or no `OPENAI_API_KEY` | Set both, restart `api` |
| Alerts don't arrive | Outside the 24-hour window, or user opted out | See the 24-hour window section; check `whatsapp_push` pref |
| `whatsapp_cloud_send_failed` in logs | Expired token / bad phone id / window closed | Regenerate a permanent token (Step 2) |
| Meta reports webhook delivery failures; logs show `whatsapp_bad_signature` (403) | `WHATSAPP_APP_SECRET` wrong or from a different Meta app | Re-copy it from Settings → Basic → App secret, restart `api` |
