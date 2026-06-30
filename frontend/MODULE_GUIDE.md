# Building an ERP module

This frontend is an **application shell + design system**. Every module plugs into the
same frame and is assembled from shared, reusable components — you should rarely hand-roll
a table, a card, or a layout. This guide covers the design tokens and the standard way to
build a list page, a detail page, a dashboard, and how to extend global search.

---

## 1. Design tokens (never hard-code colors)

Tokens live in `tailwind.config.js` and `src/index.css`. Components use **semantic
classes**, which automatically adapt to light/dark (the `.dark` class on `<html>` is
toggled by `ThemeProvider`, see `src/lib/theme.tsx`).

| Purpose            | Class                          |
| ------------------ | ------------------------------ |
| App background     | `bg-canvas`                    |
| Card / panel       | `bg-surface`                   |
| Popover / menu     | `bg-elevated`                  |
| Primary text       | `text-content`                 |
| Secondary text     | `text-muted`                   |
| Tertiary / hints   | `text-subtle`                  |
| Hairline border    | `border-line`                  |
| Stronger divider   | `border-strong`                |
| Primary action     | `bg-brand-600` / `text-brand-700` |
| Focus ring         | `focus-visible:ring-brand-500` |

Scale tokens: radius `rounded-card` / `rounded-pill`; shadow `shadow-card` / `shadow-pop`;
dense type `text-2xs`. The deep navy chrome (`bg-ink-900`) is intentionally theme-constant.

> Rule: if you're typing `bg-white`, `text-slate-700`, or a hex value in a component,
> reach for a token instead. That's what keeps every module consistent and dark-ready.

---

## 2. List page

Compose `ListPage` + `DataTable` (`@/components/ds`). DataTable is **server-driven**: you
own the query and hand it the current page of rows + the total; it owns search, sorting,
pagination, the column chooser, saved views, CSV export, and (optionally) row selection
with a bulk-action slot.

```tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";

export default function WidgetsPage() {
  const [table, setTable] = useState<DataTableState>(initialTableState(20));
  const { data, isFetching } = useQuery({
    queryKey: ["widgets", table.search, table.sort, table.page],
    queryFn: () => widgetApi.list({ search: table.search, page: table.page /* , sort */ }),
    placeholderData: (p) => p,
  });

  const columns: Column<Widget>[] = [
    { key: "code", header: "Code", accessor: (w) => w.code },
    { key: "name", header: "Name", accessor: (w) => w.name, render: (w) => <b>{w.name}</b> },
    { key: "total", header: "Total", align: "right", accessor: (w) => w.total },
  ];

  return (
    <ListPage<Widget>
      title="Widgets"
      description="Everything in the widget catalog."
      table={{
        columns, rows: data?.items ?? [], total: data?.total ?? 0,
        rowId: (w) => w.id, state: table, onStateChange: setTable,
        loading: isFetching && !data, storageKey: "widgets-table", exportName: "widgets",
        // bulkActions: ({ ids, clear }) => <Button onClick={() => archive(ids).then(clear)}>Archive</Button>,
      }}
    />
  );
}
```

Notes:
- `accessor` powers the default cell, CSV export, and gives a sort hint; `render` is for
  custom cells (badges, links). Provide `accessor` on every exportable column.
- Mark a column `sortable` only when your **endpoint** can sort by it (sorting is
  server-driven — DataTable emits `state.sort`, your query applies it).
- `storageKey` persists the column chooser + saved views per user/browser.
- `defaultHidden: true` keeps a column off by default (user can enable it via Columns).

See `src/pages/ProductsPage.tsx` for a real, wired example.

---

## 3. Detail page

Use `DetailScaffold` (loading/error/not-found) around a `FormLayout` (tabs + status +
right-rail slots: `activity` / `related` / `attachments` / `notes`). `Timeline` renders an
activity feed.

```tsx
import { DetailScaffold, FormLayout, Timeline } from "@/components/ds";

export default function WidgetDetailPage() {
  const { data, isLoading, error } = useQuery({ /* … */ });
  return (
    <DetailScaffold loading={isLoading} error={error} notFound={!isLoading && !data}>
      {data && (
        <FormLayout
          title={data.name}
          status={data.status}
          backTo={{ href: "/widgets", label: "Widgets" }}
          actions={<Button>Edit</Button>}
          tabs={[
            { key: "overview", label: "Overview", content: <Overview w={data} /> },
            { key: "lines", label: "Lines", content: <Lines w={data} /> },
          ]}
          activity={<Timeline items={data.events.map((e) => ({ title: e.label, time: e.at }))} />}
          related={<RelatedDocs w={data} />}
        />
      )}
    </DetailScaffold>
  );
}
```

---

## 4. Dashboard

`Section` + `Grid` + `KpiCard` + `ChartCard` (recharts under the hood — already in the
repo, no new dep). See `src/pages/AppLauncherPage.tsx`.

```tsx
<Section title="At a glance">
  <Grid cols={4}>
    <KpiCard label="Revenue" value="ZMW 1.2M" tone="brand" delta={{ value: "+8%", direction: "up" }} />
    {/* … */}
  </Grid>
  <ChartCard title="Sales by month" data={rows} xKey="month" kind="bar" series={[{ key: "total", label: "Total" }]} />
</Section>
```

---

## 5. Add the route + nav

1. Add a `<Route>` in `src/App.tsx` (inside the `AppShell` element).
2. Add a nav entry (with its `permission`) to the right group in
   `src/components/shell/Sidebar.tsx`. Empty groups hide automatically.
3. If the module has a searchable entity, register a **backend** search provider
   (see below) — it then appears in global search with no frontend change.

---

## 6. Branch & tenant context

The active branch lives in `useBranchContext()` (`src/lib/branchContext.tsx`) and the
tenant is implicit in the auth token. Scope your queries by including the branch in the
key and filter:

```tsx
const { branchId } = useBranchContext();
useQuery({ queryKey: ["widgets", branchId, table.page], queryFn: () => widgetApi.list({ branch_id: branchId }) });
```

---

## 7. Extending global search (backend)

Global search is an open registry — a module adds an entity without touching the core
endpoint. In `backend/app/search/providers.py` (or your module package), implement a
provider and register it:

```python
class WidgetSearch:
    entity = "widget"
    label = "Widgets"
    permission = P.WIDGET_READ
    async def search(self, session, query, limit):
        rows = (await session.execute(
            select(Widget.id, Widget.name).where(Widget.name.ilike(f"%{query}%")).limit(limit)
        )).all()
        return [SearchHit(entity="widget", id=str(r.id), title=r.name, href="/widgets") for r in rows]

register(WidgetSearch())
```

It's permission-gated (only users with `WIDGET_READ` see the group) and tenant-scoped by
RLS. The shell's command palette (⌘/Ctrl-K) and the `/search` endpoint pick it up
automatically.

---

## Component reference (`@/components/ds`)

| Component        | Use                                                        |
| ---------------- | ---------------------------------------------------------- |
| `DataTable`      | Server-driven table (search/sort/page/columns/views/CSV)  |
| `ListPage`       | Page heading + DataTable                                   |
| `FormLayout`     | Tabbed detail with status + activity/related/notes rail    |
| `DetailScaffold` | Loading / error / not-found wrapper for detail pages       |
| `KpiCard`        | Dashboard metric tile (tone + delta)                       |
| `ChartCard`      | Line/bar/area chart (recharts wrapper)                     |
| `Section`,`Grid` | Page layout primitives                                     |
| `Panel`          | Token-based surface/card                                   |
| `EmptyState`,`Skeleton` | Empty + loading states                              |
| `PageHeading`    | Token-based title bar                                      |

Shell chrome lives in `src/components/shell/` (Sidebar, TopBar, GlobalSearch,
NotificationsBell, AssistantPanel, BranchSwitcher, TenantSwitcher, UserMenu, ThemeToggle).
