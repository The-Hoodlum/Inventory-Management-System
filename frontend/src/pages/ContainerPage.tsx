import { useMutation, useQuery } from "@tanstack/react-query";
import { Container, Plus, Truck, X } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, StatCard } from "@/components/ui";
import { containerApi, type PlanLineInput } from "@/lib/container";
import { reorderApi } from "@/lib/reorder";
import { useProducts } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

interface Line {
  product_id: string;
  qty: number;
  mode: "cartons" | "units";
}

function utilTone(v: string): string {
  const n = Number(v);
  if (n >= 0.85) return "bg-emerald-500";
  if (n >= 0.6) return "bg-brand-500";
  return "bg-amber-500";
}

function UtilBar({ label, value }: { label: string; value: string }) {
  const n = Number(value) || 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>{label}</span>
        <span className="tabular">{Math.round(n * 100)}%</span>
      </div>
      <div className="mt-1 h-2 w-full rounded-full bg-slate-100">
        <div className={`h-2 rounded-full ${utilTone(value)}`} style={{ width: `${Math.min(100, n * 100)}%` }} />
      </div>
    </div>
  );
}

export default function ContainerPage() {
  const products = useProducts();
  const containers = useQuery({ queryKey: ["container", "options"], queryFn: () => containerApi.containers() });

  const [lines, setLines] = useState<Line[]>([]);
  const [pid, setPid] = useState("");
  const [qty, setQty] = useState(10);
  const [mode, setMode] = useState<"cartons" | "units">("cartons");
  const [containerCode, setContainerCode] = useState("");

  const plan = useMutation({
    mutationFn: (body: { lines: PlanLineInput[]; recs?: false } | { recs: true }) => {
      const code = containerCode || null;
      if ("recs" in body) {
        return (async () => {
          const recs = await reorderApi.recommendations({ status: "pending", page_size: 200 });
          const ids = recs.items.map((r) => r.id);
          return containerApi.planFromRecs({ recommendation_ids: ids, container_code: code });
        })();
      }
      return containerApi.plan({ lines: body.lines, container_code: code });
    },
  });

  const addLine = () => {
    if (!pid || qty <= 0) return;
    setLines((ls) => [...ls, { product_id: pid, qty, mode }]);
    setPid("");
  };
  const removeLine = (i: number) => setLines((ls) => ls.filter((_, idx) => idx !== i));

  const sku = (id: string) => products.map.get(id)?.sku ?? id.slice(0, 8);
  const runPlan = () =>
    plan.mutate({
      lines: lines.map((l) => (l.mode === "cartons" ? { product_id: l.product_id, cartons: l.qty } : { product_id: l.product_id, units: l.qty })),
    });

  const r = plan.data;

  return (
    <div>
      <PageHeader
        title="Container Load Planner"
        description="Plan a 20ft/40ft ocean-container load from carton dimensions — utilisation, the binding constraint, and how much more fits."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Builder */}
        <Card className="p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Truck className="h-4 w-4 text-brand-500" /> Build a shipment
          </h2>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <select className={`${INPUT} min-w-[10rem] flex-1`} value={pid} onChange={(e) => setPid(e.target.value)}>
              <option value="">Product…</option>
              {products.list.map((p) => (
                <option key={p.id} value={p.id}>{p.sku ?? p.name}</option>
              ))}
            </select>
            <input type="number" min={1} className={`${INPUT} w-20`} value={qty} onChange={(e) => setQty(Number(e.target.value))} />
            <select className={INPUT} value={mode} onChange={(e) => setMode(e.target.value as "cartons" | "units")}>
              <option value="cartons">cartons</option>
              <option value="units">units</option>
            </select>
            <Button variant="secondary" onClick={addLine} disabled={!pid}>
              <Plus className="h-4 w-4" /> Add
            </Button>
          </div>

          {lines.length > 0 && (
            <ul className="mt-3 divide-y divide-slate-100 rounded-lg border border-slate-100">
              {lines.map((l, i) => (
                <li key={i} className="flex items-center justify-between px-3 py-1.5 text-sm">
                  <span className="text-slate-700">{sku(l.product_id)} — {l.qty} {l.mode}</span>
                  <button className="text-slate-400 hover:text-red-500" onClick={() => removeLine(i)}>
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <select className={INPUT} value={containerCode} onChange={(e) => setContainerCode(e.target.value)}>
              <option value="">Recommend best</option>
              {(containers.data ?? []).map((c) => (
                <option key={c.code} value={c.code}>{c.label}</option>
              ))}
            </select>
            <Button onClick={runPlan} disabled={plan.isPending || lines.length === 0}>
              {plan.isPending ? "Planning…" : "Plan load"}
            </Button>
            <Button variant="ghost" onClick={() => plan.mutate({ recs: true })} disabled={plan.isPending}>
              Plan pending reorders
            </Button>
          </div>
          {plan.isError && <p className="mt-3 text-sm text-red-600">{(plan.error as Error).message}</p>}
        </Card>

        {/* Result */}
        <Card className="p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Container className="h-4 w-4 text-brand-500" /> Load plan
          </h2>
          {!r ? (
            <p className="mt-3 text-sm text-slate-400">Add lines (or use pending reorders) and click Plan.</p>
          ) : (
            <div className="mt-3 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="Container" value={r.container_code} hint={r.container_label} />
                <StatCard label="Containers" value={r.containers_needed} hint={`${r.total_cartons} cartons · binds on ${r.binding_constraint}`} />
              </div>
              <UtilBar label="Volume utilisation" value={r.volume_utilization} />
              <UtilBar label="Weight utilisation" value={r.weight_utilization} />
              <div className="text-xs text-slate-500">
                {Number(r.total_volume_m3).toFixed(2)} m³ · {Number(r.total_weight_kg).toFixed(0)} kg ·
                spare {Number(r.spare_volume_m3).toFixed(2)} m³ / {Number(r.spare_weight_kg).toFixed(0)} kg
              </div>
              {r.top_off && (
                <div className="rounded-lg border border-brand-100 bg-brand-50 px-3 py-2 text-sm text-brand-800">
                  {r.top_off.note}
                </div>
              )}
              {r.skipped_product_ids.length > 0 && (
                <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  {r.skipped_product_ids.length} product(s) skipped — no carton volume/weight set.
                </div>
              )}
              {r.lines.length > 0 && (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
                    <tr><th className="py-1 font-medium">SKU</th><th className="py-1 text-right font-medium">Cartons</th><th className="py-1 text-right font-medium">m³</th><th className="py-1 text-right font-medium">kg</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {r.lines.map((l) => (
                      <tr key={l.product_id}>
                        <td className="py-1.5 text-slate-700">{l.sku}</td>
                        <td className="py-1.5 text-right tabular">{l.cartons}</td>
                        <td className="py-1.5 text-right tabular text-slate-500">{Number(l.volume_m3).toFixed(2)}</td>
                        <td className="py-1.5 text-right tabular text-slate-500">{Number(l.weight_kg).toFixed(0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
