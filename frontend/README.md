# Inventory & Procurement — Web

React + TypeScript + Vite front end for the Inventory & Procurement API. Styled
with Tailwind CSS; data fetching with React Query; charts with Recharts.

## Prerequisites

- Node.js 18+ and npm
- The backend running and reachable (default `http://localhost:8000`). See
  `../backend/README.md` (`docker compose up --build`).

## Setup

```bash
cd frontend
npm install
cp .env.example .env          # adjust VITE_API_BASE_URL if your API is elsewhere
npm run dev                   # http://localhost:5173
```

Sign in with the demo account from the database seed:
**`admin@demo.com` / `ChangeMe123!`**

> CORS: the backend already allows `http://localhost:5173` in development. If you
> change the dev port, add it to the backend's `CORS_ORIGINS`.

## Scripts

- `npm run dev` — start the dev server
- `npm run build` — type-check and build to `dist/`
- `npm run preview` — preview the production build
- `npm run lint` — type-check only (`tsc --noEmit`)

## Structure

```
src/
├── main.tsx              app entry (Router, React Query, Auth providers)
├── App.tsx              route table
├── index.css           Tailwind layers + base styles
├── lib/
│   ├── api.ts          fetch client: token store, auto-refresh, error envelope
│   └── format.ts       number / quantity / money / date formatters
├── types/api.ts        TypeScript types mirroring the API schemas
├── auth/
│   ├── AuthContext.tsx login / logout / current user / permission checks
│   └── ProtectedRoute.tsx
├── components/
│   ├── AppShell.tsx    sidebar + top bar + content
│   ├── Sidebar.tsx     role-aware navigation (filtered by permissions)
│   ├── PageHeader.tsx
│   └── ui.tsx          Card, StatCard, StatusBadge, Button, Spinner
└── pages/
    ├── LoginPage.tsx
    ├── DashboardPage.tsx     KPIs + PO-by-status chart (wired to /dashboard/metrics)
    ├── PlaceholderPage.tsx   stub for screens being built next
    └── NotFoundPage.tsx
```

## Status

This is the **foundation**: authentication, the app shell with role-aware
navigation, and a working dashboard. The feature screens (products, suppliers,
warehouses, inventory, reorder, and the purchase-order lifecycle) are stubbed and
being built next — their backend APIs already exist.

## Auth model

Tokens (access + refresh) are stored in `localStorage`. The API client attaches
the access token, and on a `401` it transparently refreshes once and retries; if
refresh fails, it clears the session and the app returns to the sign-in screen.
Navigation items are shown based on the signed-in user's permissions from
`GET /auth/me`.
