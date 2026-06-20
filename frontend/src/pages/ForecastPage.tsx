import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LineChart, Play, Search } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard, StatusBadge } from "@/components/ui";
import { forecastApi } from "@/lib/forecast";
import { formatNumber } from "@/lib/format";
import { useProducts, useWarehouses } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function pct(v: string | number | null): string {
  if (v === null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : "—";
}

function riskTone(v: string | number | null): "danger" | "warning" | "positive" {
  const n = v === null ? 0 : Number(v);
  if (n >= 0.5) return "danger";
  if (n >= 0.25) return "warning";
  return "positive";
}

export default function ForecastPage() {
  const { hasPermission } = useAuth();
  const canRun = hasPermission("reorder.run");
  const qc = useQueryClient();
  const warehouses = useWarehouses();
  const products = useProducts();

  const summary = useQuery({ queryKey: ["forecast", "summary"], queryFn: () => forecastApi.summary() });
  const providers = useQuery({ queryKey: ["forecast", "providers"], queryFn: () => forecastApi.providers() });

  const [wh, setWh] = useState("");
  const [method, setMethod] = useState("auto");
  const [msg, setMsg] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: () => forecastApi.run({ warehouse_id: wh, method }),
    onSuccess: (r) => {
      setMsg(`Generated ${r.generated} forecast(s) using "${r.method}".`);
      qc.invalidateQueries({ queryKey: ["forecast", "summary"] });
    },
    onError: (e) => setMsg((e as Error).message),
  });

  const d = summary.data;
  const productName = (id: string) => products.map.get(id)?.sku ?? id.slice(0, 8);

  return (
    <div>
      <PageHeader
        title="Demand Forecasting"
        description="Provider-based forecasts (moving average, smoothing, Croston, seasonal) with confidence and risk."
        actions={
          canRun ? (
            <div className="flex items-center gap-2">
              <select className={INPUT} value={wh} onChange={(e) => setWh(e.target.value)}>
                <option value="">Warehouse…</option>
                {warehouses.list.map((w) => (
                  <option key={w.id} value={w.id}>{w.code ?? w.name}</option>
                ))}
              </select>
              <select className={INPUT} value={method} onChange={(e) => setMethod(e.target.value)}>
                {(providers.data ?? []).map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
              <Button onClick={() => run.mutate()} disabled={run.isPending || !wh}>
                <Play className="h-4 w-4" /> {run.isPending ? "Running…" : "Run"}
              </Button>
            </div>
          ) : undefined
        }
      />

      {msg && (
        <div className="mb-4 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-700">
          {msg}
        </div>
      )}

      {summary.isLoading ? (
        <Spinner label="Loading forecasts…" />
      ) : !d ? (
        <Card className="p-8 text-center text-sm text-slate-500">No forecast summary available.</Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Pairs Forecasted" value={formatNumber(d.pairs_forecasted)} hint={`${d.total_forecasts} total runs`} />
            <StatCard label="Avg Confidence" value={pct(d.avg_confidence)} />
            <StatCard label="Avg Risk" value={pct(d.avg_risk_score)} tone={riskTone(d.avg_risk_score)} />
            <StatCard label="High-Risk" value={formatNumber(d.high_risk_count)} tone={d.high_risk_count > 0 ? "warning" : "default"} hint="risk ≥ 50%" />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <Card className="p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <LineChart className="h-4 w-4 text-brand-500" /> Methods in use
              </h2>
              {Object.keys(d.by_method).length === 0 ? (
                <p className="mt-3 text-sm text-slate-400">No forecasts yet — run one above.</p>
              ) : (
                <ul className="mt-3 space-y-1.5 text-sm">
                  {Object.entries(d.by_method).sort((a, b) => b[1] - a[1]).map(([m, n]) => (
                    <li key={m} className="flex justify-between">
                      <span className="capitalize text-slate-600">{m.replace(/_/g, " ")}</span>
                      <span className="tabular text-slate-900">{n}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card className="overflow-hidden lg:col-span-2">
              <div className="border-b border-slate-200 px-5 py-3 text-sm font-semibold text-slate-900">
                Recent forecasts
              </div>
              {d.recent.length === 0 ? (
                <div className="p-8 text-center text-sm text-slate-400">None yet.</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-5 py-2 font-medium">Product</th>
                      <th className="px-5 py-2 font-medium">Method</th>
                      <th className="px-5 py-2 text-right font-medium">Daily</th>
                      <th className="px-5 py-2 text-right font-medium">Conf.</th>
                      <th className="px-5 py-2 text-right font-medium">Risk</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.recent.map((f) => (
                      <tr key={f.id} className="hover:bg-slate-50">
                        <td className="px-5 py-2 text-slate-700">{productName(f.product_id)}</td>
                        <td className="px-5 py-2"><StatusBadge status={f.method} /></td>
                        <td className="px-5 py-2 text-right tabular">{Number(f.adjusted_daily_demand).toFixed(1)}</td>
                        <td className="px-5 py-2 text-right tabular text-slate-500">{pct(f.confidence)}</td>
                        <td className="px-5 py-2 text-right tabular">{pct(f.risk_score)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <DemandAnalyzer />
        </>
      )}
    </div>
  );
}

function DemandAnalyzer() {
  const warehouses = useWarehouses();
  const products = useProducts();
  const [pid, setPid] = useState("");
  const [wid, setWid] = useState("");

  const analyze = useMutation({
    mutationFn: () => forecastApi.analyze({ product_id: pid, warehouse_id: wid }),
  });
  const p = analyze.data;

  return (
    <Card className="mt-6 p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Search className="h-4 w-4 text-brand-500" /> Demand-pattern analysis
      </h2>
      <p className="mt-1 text-xs text-slate-500">
        Detects intermittency (ADI/CV²), trend, and seasonality, and suggests a forecast method.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select className={INPUT} value={pid} onChange={(e) => setPid(e.target.value)}>
          <option value="">Product…</option>
          {products.list.map((pr) => (
            <option key={pr.id} value={pr.id}>{pr.sku ?? pr.name}</option>
          ))}
        </select>
        <select className={INPUT} value={wid} onChange={(e) => setWid(e.target.value)}>
          <option value="">Warehouse…</option>
          {warehouses.list.map((w) => (
            <option key={w.id} value={w.id}>{w.code ?? w.name}</option>
          ))}
        </select>
        <Button variant="secondary" onClick={() => analyze.mutate()} disabled={analyze.isPending || !pid || !wid}>
          {analyze.isPending ? "Analyzing…" : "Analyze"}
        </Button>
      </div>
      {analyze.isError && <p className="mt-3 text-sm text-red-600">{(analyze.error as Error).message}</p>}
      {p && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Classification"><StatusBadge status={p.classification} /></Field>
          <Field label="Trend">{p.trend_direction} ({pctNum(p.trend_strength)})</Field>
          <Field label="Seasonal">{p.seasonal ? `yes (period ${p.seasonal_period}d)` : "no"}</Field>
          <Field label="Suggested method"><StatusBadge status={p.suggested_method} /></Field>
          <div className="sm:col-span-2 lg:col-span-4 text-xs text-slate-500">
            {p.days_with_demand}/{p.observations} days with demand · drivers: {p.drivers.join("; ") || "—"}
          </div>
        </div>
      )}
    </Card>
  );
}

function pctNum(v: string): string {
  const n = Number(v);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : "—";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-sm text-slate-800">{children}</div>
    </div>
  );
}
