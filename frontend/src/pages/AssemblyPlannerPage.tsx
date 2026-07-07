// Assembly Planner — deterministic recommendation of which bikes to assemble from CURRENT
// stock (assembled vs unassembled counts). Thin + buildable combos are recommendations
// (assemble up to target, capped by unassembled on hand); thin combos with nothing to
// build from are surfaced separately as a purchase/import signal. No demand prediction.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Hammer, Settings2, Trash2, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type AssemblyLine, type AssemblyTargetInput, assemblyApi } from "@/lib/assembly";
import { useMotoColours, useMotoModels } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";

const INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function comboLabel(l: AssemblyLine): string {
  return [l.model_name ?? "—", l.colour_name, l.variant_name].filter(Boolean).join(" · ");
}

export default function AssemblyPlannerPage() {
  const { hasPermission } = useAuth();
  const canConfig = hasPermission("motorcycle.config");
  const canManage = hasPermission("motorcycle.manage");
  const { list: branches } = useBranches();
  const models = useMotoModels();
  const [branchId, setBranchId] = useState("");
  const [modelId, setModelId] = useState("");
  const [showTargets, setShowTargets] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["assembly", "plan", branchId, modelId],
    queryFn: () => assemblyApi.plan({ branch_id: branchId || undefined, model_id: modelId || undefined }),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader
        title="Assembly Planner"
        description="Which bikes to assemble, computed from current stock — thin assembled models that you hold unassembled units to build from. It counts what you have; it does not predict demand."
        actions={canConfig ? <Button variant="secondary" onClick={() => setShowTargets(true)}><Settings2 className="h-4 w-4" /> Targets</Button> : undefined}
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <select className={`${INPUT} w-auto`} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
          <option value="">All branches</option>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select className={`${INPUT} w-auto`} value={modelId} onChange={(e) => setModelId(e.target.value)}>
          <option value="">All models</option>
          {(models.data?.items ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        {isFetching && <Spinner />}
        {data && <span className="ml-auto text-xs text-slate-400">Keep target default {data.default_target_assembled}, flag at ≤ {data.default_threshold}</span>}
      </Card>

      {/* Recommendations */}
      <Card className="mb-4 overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2.5">
          <Hammer className="h-4 w-4 text-brand-600" />
          <span className="text-sm font-semibold text-slate-700">Assemble now</span>
          {data && <span className="text-xs text-slate-400">{data.recommendations.length} recommendation{data.recommendations.length === 1 ? "" : "s"}</span>}
        </div>
        {!data ? (
          <div className="flex h-32 items-center justify-center"><Spinner label="Computing…" /></div>
        ) : data.recommendations.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-400"><Wrench className="mx-auto mb-2 h-6 w-6 text-slate-300" />Nothing to assemble — assembled stock is at or above target where you hold buildable units.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Model · colour · variant</th>
                <th className="px-4 py-2.5 text-right font-medium">Assembled</th>
                <th className="px-4 py-2.5 text-right font-medium">Unassembled</th>
                <th className="px-4 py-2.5 text-right font-medium">Target</th>
                <th className="px-4 py-2.5 text-right font-medium">Assemble</th>
                <th className="px-4 py-2.5 font-medium">Why</th>
                {canManage && <th className="px-4 py-2.5" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.recommendations.map((l, i) => (
                <tr key={`${l.model_id}-${l.colour_id}-${l.variant_id}-${i}`}>
                  <td className="px-4 py-3 font-medium text-slate-800">{comboLabel(l)}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{l.current_assembled}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{l.unassembled_available}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-400">{l.target_assembled}</td>
                  <td className="px-4 py-3 text-right"><span className="inline-flex min-w-7 justify-center rounded-pill bg-brand-50 px-2 py-0.5 font-mono text-[13px] font-semibold text-brand-700">{l.recommended_qty}</span></td>
                  <td className="px-4 py-3 max-w-md text-xs text-slate-500">{l.reason}</td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      <Link to={`/motorcycles?model=${l.model_id}`} className="whitespace-nowrap text-xs font-medium text-brand-600 hover:underline">Assemble →</Link>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Gaps — thin, nothing to build from */}
      {data && data.gaps.length > 0 && (
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50/60 px-4 py-2.5">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            <span className="text-sm font-semibold text-amber-800">Low, nothing to assemble from</span>
            <span className="text-xs text-amber-600">{data.gaps.length} — consider purchase / import</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Model · colour · variant</th>
                <th className="px-4 py-2.5 text-right font-medium">Assembled</th>
                <th className="px-4 py-2.5 text-right font-medium">Unassembled</th>
                <th className="px-4 py-2.5 text-right font-medium">Target</th>
                <th className="px-4 py-2.5 font-medium">Why</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.gaps.map((l, i) => (
                <tr key={`${l.model_id}-${l.colour_id}-${l.variant_id}-${i}`}>
                  <td className="px-4 py-3 font-medium text-slate-800">{comboLabel(l)}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{l.current_assembled}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-400">{l.unassembled_available}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-400">{l.target_assembled}</td>
                  <td className="px-4 py-3 max-w-md text-xs text-slate-500">{l.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {showTargets && <TargetsModal onClose={() => setShowTargets(false)} />}
    </div>
  );
}

// ---- targets (per model/colour tuning) ------------------------------------
function TargetsModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const models = useMotoModels();
  const colours = useMotoColours();
  const targets = useQuery({ queryKey: ["assembly", "targets"], queryFn: () => assemblyApi.listTargets() });
  const [modelId, setModelId] = useState("");
  const [colourId, setColourId] = useState("");
  const [target, setTarget] = useState(2);
  const [threshold, setThreshold] = useState(1);
  const [err, setErr] = useState<string | null>(null);

  const modelName = useMemo(() => (m: string) => (models.data?.items ?? []).find((x) => x.id === m)?.name ?? m, [models.data]);
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ["assembly"] }); };

  const save = useMutation({
    mutationFn: () => {
      const body: AssemblyTargetInput = { model_id: modelId, colour_id: colourId || null, target_assembled: target, threshold };
      return assemblyApi.upsertTarget(body);
    },
    onSuccess: () => { invalidate(); setModelId(""); setColourId(""); setTarget(2); setThreshold(1); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the target."),
  });
  const remove = useMutation({ mutationFn: (id: string) => assemblyApi.deleteTarget(id), onSuccess: invalidate });

  return (
    <Modal title="Assembly targets" size="lg" onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Done</Button>}>
      <div className="space-y-4">
        <p className="text-xs text-slate-500">Tune how many assembled units to keep, per model (optionally per colour). Combos with no override use the global default (keep 2, flag at ≤ 1).</p>
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <label className="col-span-2 block text-sm md:col-span-1"><span className="mb-1 block font-medium text-slate-700">Model *</span>
            <select className={INPUT} value={modelId} onChange={(e) => setModelId(e.target.value)}>
              <option value="">Select…</option>
              {(models.data?.items ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <label className="col-span-2 block text-sm md:col-span-1"><span className="mb-1 block font-medium text-slate-700">Colour</span>
            <select className={INPUT} value={colourId} onChange={(e) => setColourId(e.target.value)}>
              <option value="">All colours</option>
              {(colours.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Keep (target)</span>
            <input type="number" min={1} className={INPUT} value={target} onChange={(e) => setTarget(Math.max(1, Number(e.target.value)))} />
          </label>
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Flag at ≤</span>
            <input type="number" min={0} className={INPUT} value={threshold} onChange={(e) => setThreshold(Math.max(0, Number(e.target.value)))} />
          </label>
        </div>
        <Button disabled={!modelId || save.isPending} onClick={() => { setErr(null); save.mutate(); }}>{save.isPending ? "Saving…" : "Save target"}</Button>

        <div className="rounded-lg border border-slate-200">
          {!targets.data ? (
            <div className="p-4"><Spinner label="Loading…" /></div>
          ) : targets.data.length === 0 ? (
            <div className="p-4 text-center text-sm text-slate-400">No overrides — all models use the global default.</div>
          ) : (
            <table className="w-full text-sm">
              <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">Model</th><th className="px-3 py-2 font-medium">Colour</th>
                <th className="px-3 py-2 text-right font-medium">Keep</th><th className="px-3 py-2 text-right font-medium">Flag ≤</th><th className="px-3 py-2" />
              </tr></thead>
              <tbody className="divide-y divide-slate-100">
                {targets.data.map((t) => (
                  <tr key={t.id}>
                    <td className="px-3 py-2">{t.model_name ?? modelName(t.model_id)}</td>
                    <td className="px-3 py-2 text-slate-500">{t.colour_name ?? "All"}</td>
                    <td className="px-3 py-2 text-right font-mono">{t.target_assembled}</td>
                    <td className="px-3 py-2 text-right font-mono">{t.threshold}</td>
                    <td className="px-3 py-2 text-right"><button className="text-slate-400 hover:text-red-600" onClick={() => remove.mutate(t.id)}><Trash2 className="h-4 w-4" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Modal>
  );
}
