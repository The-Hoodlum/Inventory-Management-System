// Assembly Queue — bikes that were SOLD before assembly and still owe assembly before they
// can be delivered (assembly_pending). It's the operational backlog for the workshop: each
// row is a customer waiting on an assembled bike. "Mark assembled" records the assembly (the
// shared, independent fact) and clears it from the queue. Reseller sales never appear here —
// the buyer assembles those themselves.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Hammer, PackageCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type MotoUnit, motorcyclesApi, useMotoModels } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";

const SELECT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function bikeLabel(u: { model_name: string | null; colour_name: string | null }) {
  return [u.model_name ?? "—", u.colour_name].filter(Boolean).join(" · ");
}

export default function AssemblyQueuePage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("motorcycle.manage");
  const { list: branches } = useBranches();
  const models = useMotoModels();
  const qc = useQueryClient();

  const [branchId, setBranchId] = useState("");
  const [modelId, setModelId] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const { data, isFetching } = useQuery({
    queryKey: ["assembly-queue", branchId, modelId],
    queryFn: () =>
      motorcyclesApi.listUnits({
        assembly_pending: true,
        branch_id: branchId || undefined,
        model_id: modelId || undefined,
        page_size: 200,
      }),
    placeholderData: (p) => p,
  });

  const assemble = useMutation({
    mutationFn: (id: string) => motorcyclesApi.assemble(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["assembly-queue"] });
      void qc.invalidateQueries({ queryKey: ["moto", "units"] });
      void qc.invalidateQueries({ queryKey: ["bike-pos-units"] });
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not mark the bike assembled."),
  });

  const rows = data?.items ?? [];

  return (
    <div>
      <PageHeader
        title="Assembly Queue"
        description="Bikes sold before assembly that still owe assembly before delivery. Assemble one to clear it and unblock dispatch."
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <select className={SELECT} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
          <option value="">All branches</option>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select className={SELECT} value={modelId} onChange={(e) => setModelId(e.target.value)}>
          <option value="">All models</option>
          {(models.data?.items ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        {isFetching && <Spinner />}
        <span className="ml-auto text-xs text-slate-400">
          {rows.length} bike{rows.length === 1 ? "" : "s"} awaiting assembly
        </span>
      </Card>

      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <Card className="overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2.5">
          <Hammer className="h-4 w-4 text-orange-600" />
          <span className="text-sm font-semibold text-slate-700">Awaiting assembly</span>
        </div>
        {!data ? (
          <div className="flex h-32 items-center justify-center"><Spinner label="Loading queue…" /></div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <PackageCheck className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            Nothing waiting — every sold bike has been assembled.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Chassis</th>
                  <th className="px-4 py-2.5 font-medium">Bike</th>
                  <th className="px-4 py-2.5 font-medium">Customer</th>
                  <th className="px-4 py-2.5 font-medium">Invoice</th>
                  <th className="px-4 py-2.5 font-medium">Branch</th>
                  {canManage && <th className="px-4 py-2.5 text-right font-medium">Action</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((u: MotoUnit) => (
                  <tr key={u.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-xs text-slate-700">
                      <Link to={`/motorcycles/${u.id}`} className="text-brand-600 hover:underline">{u.chassis_number}</Link>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{bikeLabel(u)}</td>
                    <td className="px-4 py-3 text-slate-600">{u.customer_name ?? "—"}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">{u.sold_invoice_number ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-600">{u.branch_name ?? "—"}</td>
                    {canManage && (
                      <td className="px-4 py-3 text-right">
                        <Button
                          variant="secondary"
                          disabled={assemble.isPending && assemble.variables === u.id}
                          onClick={() => { setErr(null); assemble.mutate(u.id); }}
                        >
                          {assemble.isPending && assemble.variables === u.id ? "Marking…" : "Mark assembled"}
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
