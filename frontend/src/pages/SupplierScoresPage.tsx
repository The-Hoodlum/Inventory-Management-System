import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, RefreshCcw } from "lucide-react";
import { useState } from "react";
import { clsx } from "clsx";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import { supplierScoresApi } from "@/lib/supplierScores";

function pct(v: string | null): string {
  if (v === null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : "—";
}

function riskTone(v: string): string {
  const n = Number(v);
  if (n >= 0.5) return "text-red-600";
  if (n >= 0.25) return "text-amber-600";
  return "text-emerald-600";
}

const GRADE_TONES: Record<string, string> = {
  A: "bg-emerald-100 text-emerald-700",
  B: "bg-brand-100 text-brand-800",
  C: "bg-amber-100 text-amber-800",
  D: "bg-orange-100 text-orange-800",
  F: "bg-red-100 text-red-700",
};

function GradePill({ grade }: { grade: string }) {
  return (
    <span className={clsx("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold",
      GRADE_TONES[grade] ?? "bg-slate-100 text-slate-700")}>
      {grade}
    </span>
  );
}

export default function SupplierScoresPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("reorder.run");
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);

  const scores = useQuery({ queryKey: ["supplier-scores"], queryFn: () => supplierScoresApi.list() });

  const refresh = useMutation({
    mutationFn: () => supplierScoresApi.refresh(),
    onSuccess: (r) => {
      setMsg(`Recomputed ${r.scored} supplier scorecard(s).`);
      qc.invalidateQueries({ queryKey: ["supplier-scores"] });
    },
    onError: (e) => setMsg((e as Error).message),
  });

  const rows = scores.data ?? [];

  return (
    <div>
      <PageHeader
        title="Supplier Scorecards"
        description="Reliability, lead-time accuracy, fill rate and a blended risk grade (A–F) from PO history + active intelligence."
        actions={
          canManage ? (
            <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
              <RefreshCcw className="h-4 w-4" /> {refresh.isPending ? "Recomputing…" : "Refresh"}
            </Button>
          ) : undefined
        }
      />

      {msg && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {msg}
        </div>
      )}

      {scores.isLoading ? (
        <Spinner label="Loading scorecards…" />
      ) : rows.length === 0 ? (
        <Card className="p-8 text-center text-sm text-slate-400">
          <Award className="mx-auto mb-2 h-6 w-6 text-slate-300" />
          No scorecards yet — click Refresh to compute them from purchase-order history.
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-2 font-medium">Supplier</th>
                <th className="px-5 py-2 text-center font-medium">Grade</th>
                <th className="px-5 py-2 text-right font-medium">Risk</th>
                <th className="px-5 py-2 text-right font-medium">Reliability</th>
                <th className="px-5 py-2 text-right font-medium">On-time</th>
                <th className="px-5 py-2 text-right font-medium">Fill</th>
                <th className="px-5 py-2 text-right font-medium">POs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((s) => (
                <tr key={s.id} className="align-top hover:bg-slate-50">
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-800">{s.supplier_name}</div>
                    {s.drivers && s.drivers.length > 0 && (
                      <div className="mt-0.5 text-xs text-slate-400">{s.drivers.join(" · ")}</div>
                    )}
                  </td>
                  <td className="px-5 py-3 text-center"><GradePill grade={s.grade} /></td>
                  <td className={clsx("px-5 py-3 text-right tabular font-medium", riskTone(s.risk_score))}>{pct(s.risk_score)}</td>
                  <td className="px-5 py-3 text-right tabular text-slate-600">{pct(s.reliability)}</td>
                  <td className="px-5 py-3 text-right tabular text-slate-600">{pct(s.on_time_rate)}</td>
                  <td className="px-5 py-3 text-right tabular text-slate-600">{pct(s.fill_rate)}</td>
                  <td className="px-5 py-3 text-right tabular text-slate-500">{formatNumber(s.po_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
