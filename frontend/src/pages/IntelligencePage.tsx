import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, RefreshCcw, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard, StatusBadge } from "@/components/ui";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { intelligenceApi } from "@/lib/intelligence";
import type { IntelligenceCategory, IntelligenceScopeType, ManualSignalBody } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const CATEGORIES: IntelligenceCategory[] = [
  "freight",
  "port",
  "commodity",
  "trade",
  "supplier",
  "geopolitical",
];
const SCOPES: IntelligenceScopeType[] = ["global", "country", "supplier", "commodity", "route", "port"];

function pct(value: string | number): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

function riskTone(v: number): "danger" | "warning" | "positive" {
  if (v >= 0.5) return "danger";
  if (v >= 0.25) return "warning";
  return "positive";
}

function impactLabel(factor: number): string {
  const change = (factor - 1) * 100;
  if (Math.abs(change) < 0.05) return "no change";
  return `${change > 0 ? "+" : ""}${change.toFixed(0)}% demand`;
}

export default function IntelligencePage() {
  const { hasPermission } = useAuth();
  const qc = useQueryClient();
  const canManage = hasPermission("reorder.run");

  const [err, setErr] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const dashboard = useQuery({
    queryKey: ["intelligence", "dashboard"],
    queryFn: () => intelligenceApi.dashboard(),
  });
  const signals = useQuery({
    queryKey: ["intelligence", "signals"],
    queryFn: () => intelligenceApi.signals({ page_size: 200 }),
    placeholderData: (prev) => prev,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["intelligence", "dashboard"] });
    qc.invalidateQueries({ queryKey: ["intelligence", "signals"] });
  };

  const ingest = useMutation({
    mutationFn: () => intelligenceApi.ingest(),
    onSuccess: () => {
      setErr(null);
      invalidate();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const d = dashboard.data;
  const risk = d ? Number(d.risk_score) : 0;
  const factor = d ? Number(d.forecast_impact) : 1;

  return (
    <div>
      <PageHeader
        title="Supply Chain Intelligence"
        description="Risk signals feeding forecasts and procurement decisions."
        actions={
          canManage ? (
            <>
              <Button variant="secondary" onClick={() => setShowForm((s) => !s)}>
                <Plus className="h-4 w-4" /> Add signal
              </Button>
              <Button onClick={() => ingest.mutate()} disabled={ingest.isPending}>
                <RefreshCcw className="h-4 w-4" /> {ingest.isPending ? "Refreshing…" : "Refresh"}
              </Button>
            </>
          ) : undefined
        }
      />

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}
      {ingest.data && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Refreshed intelligence — {ingest.data.ingested} observation(s) updated.
        </div>
      )}

      {showForm && canManage && <ManualSignalForm onDone={invalidate} onError={setErr} />}

      {dashboard.isLoading ? (
        <Spinner label="Loading intelligence…" />
      ) : !d ? (
        <Card className="p-8 text-center text-sm text-slate-500">No intelligence available.</Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Supply Risk" value={pct(d.risk_score)} tone={riskTone(risk)}
              hint={risk >= 0.5 ? "Elevated" : risk >= 0.25 ? "Watch" : "Low"} />
            <StatCard label="Forecast Impact" value={impactLabel(factor)}
              tone={factor > 1 ? "warning" : "default"} hint="Composite demand factor" />
            <StatCard label="Confidence" value={pct(d.confidence)} hint="In this assessment" />
            <StatCard label="Active Signals" value={formatNumber(d.active_signals)} />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <ShieldAlert className="h-4 w-4 text-amber-500" /> Recommended actions
              </h2>
              {d.recommended_actions.length === 0 ? (
                <p className="mt-3 text-sm text-slate-400">No actions — supply risk is low.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {d.recommended_actions.map((a, i) => (
                    <li key={i} className="flex gap-2 text-sm text-slate-700">
                      <span className="mt-0.5 text-amber-500">•</span>
                      {a}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card className="p-5">
              <h2 className="text-sm font-semibold text-slate-900">Risk by category</h2>
              {Object.keys(d.by_category).length === 0 ? (
                <p className="mt-3 text-sm text-slate-400">No category risk.</p>
              ) : (
                <div className="mt-3 space-y-2.5">
                  {Object.entries(d.by_category)
                    .sort((a, b) => Number(b[1]) - Number(a[1]))
                    .map(([cat, sev]) => (
                      <div key={cat}>
                        <div className="flex justify-between text-xs text-slate-600">
                          <span className="capitalize">{cat}</span>
                          <span className="tabular">{pct(sev)}</span>
                        </div>
                        <div className="mt-1 h-2 w-full rounded-full bg-slate-100">
                          <div
                            className="h-2 rounded-full bg-brand-500"
                            style={{ width: `${Math.min(100, Number(sev) * 100)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </Card>
          </div>

          <Card className="mt-6 overflow-hidden">
            <div className="border-b border-slate-200 px-5 py-3 text-sm font-semibold text-slate-900">
              Active signals
            </div>
            {signals.isLoading ? (
              <div className="p-5"><Spinner /></div>
            ) : (signals.data?.items.length ?? 0) === 0 ? (
              <div className="p-8 text-center text-sm text-slate-400">
                No signals yet. Refresh to compute supplier risk, or add one manually.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-5 py-2 font-medium">Category</th>
                    <th className="px-5 py-2 font-medium">Scope</th>
                    <th className="px-5 py-2 font-medium">Signal</th>
                    <th className="px-5 py-2 text-right font-medium">Severity</th>
                    <th className="px-5 py-2 text-right font-medium">Confidence</th>
                    <th className="px-5 py-2 font-medium">Source</th>
                    <th className="px-5 py-2 font-medium">Observed</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {signals.data?.items.map((s) => (
                    <tr key={s.id} className="hover:bg-slate-50">
                      <td className="px-5 py-2"><StatusBadge status={s.category} /></td>
                      <td className="px-5 py-2 text-slate-500">
                        {s.scope_type}{s.scope_key ? `: ${s.scope_key.slice(0, 12)}` : ""}
                      </td>
                      <td className="px-5 py-2 text-slate-700">
                        {s.trend === "up" && <AlertTriangle className="mr-1 inline h-3.5 w-3.5 text-red-500" />}
                        {s.headline}
                      </td>
                      <td className="px-5 py-2 text-right tabular">{pct(s.severity)}</td>
                      <td className="px-5 py-2 text-right tabular text-slate-500">{pct(s.confidence)}</td>
                      <td className="px-5 py-2 text-slate-500">{titleCase(s.source)}</td>
                      <td className="px-5 py-2 text-slate-500">{formatDate(s.observed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function ManualSignalForm({
  onDone,
  onError,
}: {
  onDone: () => void;
  onError: (m: string) => void;
}) {
  const [form, setForm] = useState<ManualSignalBody>({
    category: "freight",
    scope_type: "country",
    scope_key: "",
    severity: 0.5,
    demand_factor: 1,
    headline: "",
  });

  const save = useMutation({
    mutationFn: () =>
      intelligenceApi.recordSignal({ ...form, scope_key: form.scope_key || null }),
    onSuccess: () => {
      onError("");
      setForm((f) => ({ ...f, headline: "", scope_key: "" }));
      onDone();
    },
    onError: (e) => onError((e as Error).message),
  });

  return (
    <Card className="mb-6 p-5">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">Add intelligence signal</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-xs text-slate-600">
          Category
          <select
            className={`${INPUT} mt-1 w-full`}
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value as IntelligenceCategory })}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{titleCase(c)}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-600">
          Scope
          <select
            className={`${INPUT} mt-1 w-full`}
            value={form.scope_type}
            onChange={(e) => setForm({ ...form, scope_type: e.target.value as IntelligenceScopeType })}
          >
            {SCOPES.map((s) => (
              <option key={s} value={s}>{titleCase(s)}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-600">
          Scope key (e.g. CN, steel)
          <input
            className={`${INPUT} mt-1 w-full`}
            value={form.scope_key ?? ""}
            onChange={(e) => setForm({ ...form, scope_key: e.target.value })}
            placeholder="optional"
          />
        </label>
        <label className="text-xs text-slate-600">
          Severity (0–1)
          <input
            type="number" min={0} max={1} step={0.05}
            className={`${INPUT} mt-1 w-full`}
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: Number(e.target.value) })}
          />
        </label>
        <label className="text-xs text-slate-600 sm:col-span-2 lg:col-span-3">
          Headline
          <input
            className={`${INPUT} mt-1 w-full`}
            value={form.headline}
            onChange={(e) => setForm({ ...form, headline: e.target.value })}
            placeholder="e.g. Ocean freight ex-CN up 35%"
          />
        </label>
        <label className="text-xs text-slate-600">
          Demand factor
          <input
            type="number" min={0.1} step={0.05}
            className={`${INPUT} mt-1 w-full`}
            value={form.demand_factor}
            onChange={(e) => setForm({ ...form, demand_factor: Number(e.target.value) })}
          />
        </label>
      </div>
      <div className="mt-4 flex justify-end">
        <Button
          onClick={() => save.mutate()}
          disabled={save.isPending || !form.headline.trim()}
        >
          {save.isPending ? "Saving…" : "Save signal"}
        </Button>
      </div>
    </Card>
  );
}
