// Global search command palette. Opens from the top bar or Ctrl/⌘-K, queries the single
// /search endpoint (which fans across every entity the user may see), and navigates to a
// hit on select. Debounced via the query key; results are grouped by entity.
import { useQuery } from "@tanstack/react-query";
import { Search as SearchIcon, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { searchApi, type SearchHit } from "@/lib/search";

export function GlobalSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const { data, isFetching } = useQuery({
    queryKey: ["search", q],
    queryFn: ({ signal }) => searchApi.query(q, signal),
    enabled: open && q.trim().length >= 2,
    placeholderData: (prev) => prev,
  });

  if (!open) return null;
  const groups = data?.groups ?? [];

  const go = (hit: SearchHit) => {
    navigate(hit.href);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[12vh]">
      <button aria-hidden className="fixed inset-0 bg-ink-950/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-xl overflow-hidden rounded-card border border-line bg-elevated shadow-pop">
        <div className="flex items-center gap-2 border-b border-line px-3">
          <SearchIcon className="h-4 w-4 text-content-subtle" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search products, customers, suppliers, sales documents…"
            className="flex-1 bg-transparent py-3 text-sm text-content placeholder:text-content-subtle focus:outline-none"
          />
          <button onClick={onClose} className="rounded p-1 text-content-subtle hover:bg-canvas">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[55vh] overflow-auto p-2">
          {q.trim().length < 2 ? (
            <p className="px-3 py-6 text-center text-sm text-content-subtle">
              Type at least 2 characters to search.
            </p>
          ) : groups.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-content-subtle">
              {isFetching ? "Searching…" : "No matches."}
            </p>
          ) : (
            groups.map((g) => (
              <div key={g.entity} className="mb-2">
                <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wide text-content-subtle">
                  {g.label}
                </div>
                {g.hits.map((hit) => (
                  <button
                    key={`${hit.entity}-${hit.id}`}
                    onClick={() => go(hit)}
                    className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-canvas"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-content">{hit.title}</span>
                      {hit.subtitle && (
                        <span className="block truncate text-xs text-muted">{hit.subtitle}</span>
                      )}
                    </span>
                    {hit.badge && (
                      <span className="shrink-0 rounded-full bg-canvas px-2 py-0.5 text-2xs capitalize text-content-muted">
                        {hit.badge.replace(/_/g, " ")}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
