// Bike Issues — record an INTERNAL repair on a bike we own and consume the spare part(s)
// used to fix it. This is NOT a customer sale: the part is an internal cost. Opening an
// issue holds the bike; resolving consumes the parts (single inventory write path) and
// returns the bike to sale.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Wrench } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type CreateBikeIssueBody, bikeIssuesApi } from "@/lib/bikeIssues";
import { catalogApi } from "@/lib/catalog";
import { formatDate } from "@/lib/format";
import { inventoryApi } from "@/lib/inventory";
import { motorcyclesApi } from "@/lib/motorcycles";
import { useBranches, useWarehouses } from "@/lib/refdata";

const INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const STATUSES = ["open", "in_repair", "resolved"] as const;

export default function BikeIssuesPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canManage = hasPermission("bike_issue.manage");
  const { list: branches } = useBranches();
  const [status, setStatus] = useState("");
  const [branchId, setBranchId] = useState("");
  const [search, setSearch] = useState("");
  const [showNew, setShowNew] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["bike-issues", "list", status, branchId, search],
    queryFn: () => bikeIssuesApi.list({
      status: status || undefined, branch_id: branchId || undefined, search: search.trim() || undefined,
    }),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader
        title="Bike Issues"
        description="Record an internal repair on a bike we own and consume the spare part(s) used. Parts are an internal cost — never a customer sale. Opening an issue holds the bike; resolving consumes the parts and returns it to sale."
        actions={canManage ? <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New repair</Button> : undefined}
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <select className={`${INPUT} w-auto`} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </select>
        <select className={`${INPUT} w-auto`} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
          <option value="">All branches</option>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <input className={`${INPUT} max-w-xs`} placeholder="Search chassis / engine / repair #" value={search} onChange={(e) => setSearch(e.target.value)} />
        {isFetching && <Spinner />}
      </Card>

      <Card className="overflow-hidden">
        {!data ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : data.items.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <Wrench className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            No repair issues.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Repair #</th>
                <th className="px-4 py-2.5 font-medium">Bike</th>
                <th className="px-4 py-2.5 font-medium">Problem</th>
                <th className="px-4 py-2.5 text-right font-medium">Parts</th>
                <th className="px-4 py-2.5 font-medium">Reported</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((i) => (
                <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/bike-issues/${i.id}`)}>
                  <td className="px-4 py-3 font-mono text-[13px] font-medium">{i.issue_number}</td>
                  <td className="px-4 py-3">
                    <span className="font-mono text-[13px] text-slate-800">{i.chassis_number}</span>
                    {i.model_name && <span className="ml-2 text-xs text-slate-400">{i.model_name}</span>}
                  </td>
                  <td className="px-4 py-3 max-w-xs truncate text-slate-600">{i.problem_description}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{i.lines.length}</td>
                  <td className="px-4 py-3 text-slate-500">{formatDate(i.reported_at)}</td>
                  <td className="px-4 py-3"><StatusBadge status={i.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {showNew && <NewRepairModal onClose={() => setShowNew(false)} onCreated={(id) => navigate(`/bike-issues/${id}`)} />}
    </div>
  );
}

interface PartRow { product_id: string; sku: string; name: string; qty: number }

function NewRepairModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const warehouses = useWarehouses();
  const [bikeSearch, setBikeSearch] = useState("");
  const [bike, setBike] = useState<{ id: string; chassis: string; engine: string | null; model: string | null } | null>(null);
  const [problem, setProblem] = useState("");
  const [notes, setNotes] = useState("");
  const [wh, setWh] = useState("");
  const [partSearch, setPartSearch] = useState("");
  const [parts, setParts] = useState<PartRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const bikeQ = useQuery({
    queryKey: ["bike-issue-bike-search", bikeSearch],
    queryFn: () => motorcyclesApi.listUnits({ search: bikeSearch.trim(), sold: false, page_size: 8 }),
    enabled: bikeSearch.trim().length >= 2,
  });
  const partQ = useQuery({
    queryKey: ["bike-issue-part-search", partSearch],
    queryFn: () => catalogApi.products({ search: partSearch.trim(), page: 1, page_size: 8 }),
    enabled: partSearch.trim().length >= 2,
  });
  const partIds = new Set(parts.map((p) => p.product_id));

  const create = useMutation({
    mutationFn: () => {
      const body: CreateBikeIssueBody = {
        unit_id: bike!.id,
        problem_description: problem.trim(),
        notes: notes.trim() || undefined,
        lines: parts.map((p) => ({ product_id: p.product_id, warehouse_id: wh, quantity: p.qty })),
      };
      return bikeIssuesApi.create(body);
    },
    onSuccess: (i) => { void qc.invalidateQueries({ queryKey: ["bike-issues"] }); onCreated(i.id); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not open the repair."),
  });

  const valid = bike && problem.trim() && (parts.length === 0 || wh);

  return (
    <Modal title="New bike repair" size="xl" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>{create.isPending ? "Opening…" : "Open repair"}</Button>
      </>
    }>
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        {/* Bike */}
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Bike (by chassis / engine) *</div>
          {bike ? (
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <span className="font-mono text-[13px] text-slate-800">{bike.chassis}</span>
              <span className="text-xs text-slate-500">Engine {bike.engine ?? "—"} · {bike.model}</span>
              <button className="ml-auto text-slate-400 hover:text-red-600" onClick={() => setBike(null)}><Trash2 className="h-4 w-4" /></button>
            </div>
          ) : (
            <>
              <input className={INPUT} placeholder="Search chassis / engine" value={bikeSearch} onChange={(e) => setBikeSearch(e.target.value)} />
              {bikeSearch.trim().length >= 2 && (
                <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200">
                  {(bikeQ.data?.items ?? []).map((u) => (
                    <button key={u.id} className="flex w-full justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                      onClick={() => { setBike({ id: u.id, chassis: u.chassis_number, engine: u.engine_number, model: u.model_name }); setBikeSearch(""); }}>
                      <span className="font-mono text-[13px]">{u.chassis_number}</span>
                      <span className="text-xs text-slate-500">{u.engine_number ?? ""} · {u.model_name}</span>
                    </button>
                  ))}
                  {(bikeQ.data?.items ?? []).length === 0 && !bikeQ.isFetching && (
                    <div className="px-3 py-2 text-xs text-slate-400">No sellable bike matches.</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <Field label="Problem / fault *">
          <textarea className={`${INPUT} min-h-[60px]`} value={problem} onChange={(e) => setProblem(e.target.value)} placeholder="Describe the fault being repaired" />
        </Field>

        {/* Parts */}
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Spare parts consumed (optional now — can add before resolving)</div>
          <Field label="Source location">
            <select className={INPUT} value={wh} onChange={(e) => setWh(e.target.value)}>
              <option value="">Select the store the parts come from…</option>
              {warehouses.list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
          {wh && (
            <>
              <input className={`${INPUT} mt-2`} placeholder="Search part (name / SKU)" value={partSearch} onChange={(e) => setPartSearch(e.target.value)} />
              {partSearch.trim().length >= 2 && (
                <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200">
                  {(partQ.data?.items ?? []).filter((p) => !partIds.has(p.id)).map((p) => (
                    <button key={p.id} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                      onClick={() => { setParts((ps) => [...ps, { product_id: p.id, sku: p.sku, name: p.name, qty: 1 }]); setPartSearch(""); }}>
                      <span>{p.name} <span className="font-mono text-xs text-slate-400">{p.sku}</span></span>
                      <StockBadge productId={p.id} warehouseId={wh} />
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
          {parts.map((p, i) => (
            <div key={p.product_id} className="mt-1 flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-slate-800">{p.name} <span className="font-mono text-xs text-slate-400">{p.sku}</span></span>
              <StockBadge productId={p.product_id} warehouseId={wh} />
              <input type="number" min={1} value={p.qty} className="w-16 rounded border border-slate-300 px-2 py-1 text-right text-sm" onChange={(e) => setParts((ps) => ps.map((x, j) => j === i ? { ...x, qty: Math.max(1, Number(e.target.value)) } : x))} />
              <button className="text-slate-400 hover:text-red-600" onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>

        <Field label="Notes"><input className={INPUT} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

// Live available stock for a part at the chosen source location.
export function StockBadge({ productId, warehouseId }: { productId: string; warehouseId: string }) {
  const { data } = useQuery({
    queryKey: ["bike-issue-stock", productId, warehouseId],
    queryFn: () => inventoryApi.list({ product_id: productId, warehouse_id: warehouseId, page_size: 1 }),
    enabled: !!productId && !!warehouseId,
  });
  const avail = data?.items?.[0]?.qty_available;
  const n = avail != null ? Number(avail) : null;
  return (
    <span className={`whitespace-nowrap text-xs ${n != null && n <= 0 ? "text-red-500" : "text-slate-400"}`}>
      {n != null ? `${n} in stock` : "—"}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">{label}</span>{children}</label>;
}
