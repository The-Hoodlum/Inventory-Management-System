// DataTable — the one table every module reuses. Generic over the row type and
// SERVER-DRIVEN: the parent owns data fetching and passes `rows` + `total` for the
// current `state` (search / sort / page), reacting to `onStateChange`. Built in:
// search, sortable headers, pagination, a column chooser, saved views, a bulk-action
// slot with row selection, and CSV export. Persists column/view choices per `storageKey`.
import { clsx } from "clsx";
import {
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Columns3,
  Download,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { EmptyState, Panel, Skeleton } from "./Panel";

export type SortDir = "asc" | "desc";

export interface DataTableState {
  search: string;
  sort: { key: string; dir: SortDir } | null;
  page: number;
  pageSize: number;
}

export const initialTableState = (pageSize = 20): DataTableState => ({
  search: "",
  sort: null,
  page: 1,
  pageSize,
});

export interface Column<Row> {
  key: string;
  header: string;
  /** Cell renderer. Falls back to the accessor's value. */
  render?: (row: Row) => ReactNode;
  /** Plain value — used for the default cell, CSV export, and as a hint for sorting. */
  accessor?: (row: Row) => string | number | null | undefined;
  sortable?: boolean;
  align?: "left" | "right" | "center";
  defaultHidden?: boolean;
  className?: string;
}

interface SavedView {
  name: string;
  state: DataTableState;
  columns: string[];
}

export interface DataTableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  total: number;
  rowId: (row: Row) => string;
  state: DataTableState;
  onStateChange: (next: DataTableState) => void;
  loading?: boolean;
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Extra filter controls rendered in the toolbar (e.g. a status <select>). */
  filters?: ReactNode;
  /** Rendered when rows are selected; receives the selected ids and a clear fn. */
  bulkActions?: (ctx: { ids: string[]; clear: () => void }) => ReactNode;
  onRowClick?: (row: Row) => void;
  /** Enables persistence of the column chooser + saved views in localStorage. */
  storageKey?: string;
  /** Enables CSV export with this filename (no extension). */
  exportName?: string;
  emptyTitle?: string;
  emptyHint?: string;
}

function readLS<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function csvCell(v: unknown): string {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Small click-away dropdown — no external dependency. */
function Menu({ label, icon, children }: { label: string; icon: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-content-muted hover:bg-canvas"
      >
        {icon}
        {label}
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-hidden
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-50 mt-1 min-w-[12rem] rounded-lg border border-line bg-elevated p-1 shadow-pop">
            {children}
          </div>
        </>
      )}
    </div>
  );
}

export function DataTable<Row>({
  columns,
  rows,
  total,
  rowId,
  state,
  onStateChange,
  loading = false,
  searchable = true,
  searchPlaceholder = "Search…",
  filters,
  bulkActions,
  onRowClick,
  storageKey,
  exportName,
  emptyTitle = "Nothing here yet",
  emptyHint,
}: DataTableProps<Row>) {
  // ---- column visibility (persisted) ----
  const allKeys = useMemo(() => columns.map((c) => c.key), [columns]);
  const [visible, setVisible] = useState<string[]>(() => {
    const initial = columns.filter((c) => !c.defaultHidden).map((c) => c.key);
    return storageKey ? readLS(`${storageKey}:cols`, initial) : initial;
  });
  useEffect(() => {
    if (storageKey) localStorage.setItem(`${storageKey}:cols`, JSON.stringify(visible));
  }, [storageKey, visible]);
  const shownColumns = columns.filter((c) => visible.includes(c.key));

  // ---- search (debounced) ----
  const [searchInput, setSearchInput] = useState(state.search);
  useEffect(() => setSearchInput(state.search), [state.search]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSearch = (value: string) => {
    setSearchInput(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => onStateChange({ ...state, search: value, page: 1 }), 300);
  };

  // ---- sorting ----
  const toggleSort = (key: string) => {
    const dir: SortDir =
      state.sort?.key === key && state.sort.dir === "asc" ? "desc" : "asc";
    onStateChange({ ...state, sort: { key, dir }, page: 1 });
  };

  // ---- selection ----
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const pageIds = rows.map(rowId);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const toggleAll = () =>
    setSelected((s) => {
      const next = new Set(s);
      if (allOnPage) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  const toggleOne = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const clearSelection = () => setSelected(new Set());

  // ---- saved views (persisted) ----
  const viewsKey = storageKey ? `${storageKey}:views` : null;
  const [views, setViews] = useState<SavedView[]>(() => (viewsKey ? readLS(viewsKey, []) : []));
  const persistViews = (next: SavedView[]) => {
    setViews(next);
    if (viewsKey) localStorage.setItem(viewsKey, JSON.stringify(next));
  };
  const saveView = () => {
    const name = window.prompt("Save current view as:");
    if (!name) return;
    persistViews([...views.filter((v) => v.name !== name), { name, state, columns: visible }]);
  };
  const applyView = (v: SavedView) => {
    setVisible(v.columns);
    onStateChange(v.state);
  };

  // ---- CSV export ----
  const exportCsv = () => {
    const cols = shownColumns.filter((c) => c.accessor);
    const header = cols.map((c) => csvCell(c.header)).join(",");
    const lines = rows.map((r) => cols.map((c) => csvCell(c.accessor!(r))).join(","));
    const blob = new Blob([[header, ...lines].join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exportName}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
  const colSpan = shownColumns.length + (bulkActions ? 1 : 0);

  return (
    <div>
      {/* Toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {searchable && (
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-subtle" />
            <input
              value={searchInput}
              onChange={(e) => onSearch(e.target.value)}
              placeholder={searchPlaceholder}
              className="w-64 rounded-lg border border-line bg-surface py-1.5 pl-8 pr-3 text-sm text-content placeholder:text-content-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            />
          </div>
        )}
        {filters}
        <div className="ml-auto flex items-center gap-2">
          {viewsKey && (
            <Menu label="Views" icon={<Save className="h-3.5 w-3.5" />}>
              {views.length === 0 && (
                <div className="px-2 py-1.5 text-xs text-content-subtle">No saved views</div>
              )}
              {views.map((v) => (
                <button
                  key={v.name}
                  onClick={() => applyView(v)}
                  className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs text-content-muted hover:bg-canvas"
                >
                  {v.name}
                  <Trash2
                    className="h-3.5 w-3.5 text-content-subtle hover:text-red-500"
                    onClick={(e) => {
                      e.stopPropagation();
                      persistViews(views.filter((x) => x.name !== v.name));
                    }}
                  />
                </button>
              ))}
              <div className="my-1 border-t border-line" />
              <button
                onClick={saveView}
                className="w-full rounded px-2 py-1.5 text-left text-xs font-medium text-brand-600 hover:bg-canvas"
              >
                Save current view…
              </button>
            </Menu>
          )}
          <Menu label="Columns" icon={<Columns3 className="h-3.5 w-3.5" />}>
            {columns.map((c) => (
              <label
                key={c.key}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs text-content-muted hover:bg-canvas"
              >
                <input
                  type="checkbox"
                  checked={visible.includes(c.key)}
                  onChange={() =>
                    setVisible((vis) =>
                      vis.includes(c.key)
                        ? vis.filter((k) => k !== c.key)
                        : allKeys.filter((k) => vis.includes(k) || k === c.key)
                    )
                  }
                />
                {c.header}
              </label>
            ))}
          </Menu>
          {exportName && (
            <button
              type="button"
              onClick={exportCsv}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-content-muted hover:bg-canvas"
            >
              <Download className="h-3.5 w-3.5" /> Export
            </button>
          )}
        </div>
      </div>

      {/* Bulk action bar */}
      {bulkActions && selected.size > 0 && (
        <div className="mb-2 flex items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-800">
          <span className="font-medium">{selected.size} selected</span>
          <div className="flex items-center gap-2">
            {bulkActions({ ids: [...selected], clear: clearSelection })}
          </div>
          <button onClick={clearSelection} className="ml-auto text-xs text-brand-700 hover:underline">
            Clear
          </button>
        </div>
      )}

      <Panel className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-canvas text-left text-xs uppercase tracking-wide text-muted">
                {bulkActions && (
                  <th className="w-10 px-3 py-2.5">
                    <input type="checkbox" checked={allOnPage} onChange={toggleAll} aria-label="Select all" />
                  </th>
                )}
                {shownColumns.map((c) => {
                  const active = state.sort?.key === c.key;
                  return (
                    <th
                      key={c.key}
                      className={clsx(
                        "px-4 py-2.5 font-medium",
                        c.align === "right" && "text-right",
                        c.align === "center" && "text-center",
                        c.sortable && "cursor-pointer select-none"
                      )}
                      onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                    >
                      <span className={clsx("inline-flex items-center gap-1", c.align === "right" && "flex-row-reverse")}>
                        {c.header}
                        {c.sortable &&
                          (active ? (
                            state.sort?.dir === "asc" ? (
                              <ArrowUp className="h-3 w-3" />
                            ) : (
                              <ArrowDown className="h-3 w-3" />
                            )
                          ) : (
                            <ChevronsUpDown className="h-3 w-3 text-content-subtle" />
                          ))}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={colSpan} className="px-4 py-3">
                      <Skeleton className="h-5 w-full" />
                    </td>
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={colSpan}>
                    <EmptyState title={emptyTitle} hint={emptyHint} />
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const id = rowId(row);
                  return (
                    <tr
                      key={id}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}
                      className={clsx(
                        "text-content-muted",
                        onRowClick && "cursor-pointer",
                        "hover:bg-canvas"
                      )}
                    >
                      {bulkActions && (
                        <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selected.has(id)}
                            onChange={() => toggleOne(id)}
                            aria-label="Select row"
                          />
                        </td>
                      )}
                      {shownColumns.map((c) => (
                        <td
                          key={c.key}
                          className={clsx(
                            "px-4 py-3",
                            c.align === "right" && "text-right",
                            c.align === "center" && "text-center",
                            c.className
                          )}
                        >
                          {c.render ? c.render(row) : (c.accessor?.(row) ?? "—")}
                        </td>
                      ))}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Pagination
        page={state.page}
        totalPages={totalPages}
        total={total}
        onChange={(p) => onStateChange({ ...state, page: p })}
      />
    </div>
  );
}
