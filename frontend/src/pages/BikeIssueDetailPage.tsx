// Bike Issue detail — the bike (chassis + engine, read from the unit), the problem, and
// the spare parts used. Add parts while the repair is open; resolving COMMITS the part
// consumption (single inventory write path) and returns the bike to its prior sellable
// status. A short part rejects the whole resolve — no negative stock.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { type BikeIssue, bikeIssuesApi } from "@/lib/bikeIssues";
import { catalogApi } from "@/lib/catalog";
import { formatDate } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { statusLabel } from "@/lib/motorcycles";
import { useWarehouses } from "@/lib/refdata";
import { StockBadge } from "@/pages/BikeIssuesPage";

const INPUT = "rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function BikeIssueDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("bike_issue.manage");
  const [err, setErr] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [note, setNote] = useState("");

  const { data: issue, isLoading } = useQuery({ queryKey: ["bike-issues", "one", id], queryFn: () => bikeIssuesApi.get(id), enabled: !!id });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["bike-issues"] }); };
  const onErr = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Action failed.");

  const start = useMutation({ mutationFn: () => bikeIssuesApi.setStatus(id, "in_repair"), onSuccess: refresh, onError: onErr });
  const resolve = useMutation({
    mutationFn: () => bikeIssuesApi.resolve(id, { resolution_note: note.trim() || undefined }),
    onSuccess: () => { setResolving(false); setNote(""); refresh(); },
    onError: onErr,
  });
  const removeLine = useMutation({ mutationFn: (lineId: string) => bikeIssuesApi.removeLine(id, lineId), onSuccess: refresh, onError: onErr });

  if (isLoading || !issue) return <div><PageHeader title="Bike repair" /><div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div></div>;

  const active = issue.status === "open" || issue.status === "in_repair";

  return (
    <div>
      <PageHeader
        title={issue.issue_number}
        description="Internal repair — parts consumed here are an internal cost, never a customer sale."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => navigate("/bike-issues")}>Back</Button>
            {canManage && issue.status === "open" && <Button variant="secondary" disabled={start.isPending} onClick={() => { setErr(null); start.mutate(); }}>{start.isPending ? "…" : "Start repair"}</Button>}
            {canManage && active && !resolving && <Button onClick={() => { setErr(null); setResolving(true); }}>Resolve…</Button>}
          </div>
        }
      />
      {err && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <Card className="mb-4 p-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm md:grid-cols-4">
          <Info label="Status"><StatusBadge status={issue.status} /></Info>
          <Info label="Bike">
            <Link to={`/motorcycles/${issue.unit_id}`} className="font-mono text-[13px] text-brand-600 hover:underline">{issue.chassis_number}</Link>
          </Info>
          <Info label="Engine"><span className="font-mono">{issue.engine_number ?? "—"}</span></Info>
          <Info label="Model">{issue.model_name ?? "—"}</Info>
          <Info label="Branch">{issue.branch_name ?? "—"}</Info>
          <Info label="Reported">{formatDate(issue.reported_at)}</Info>
          <Info label="Returns to">{statusLabel(issue.prior_status)}</Info>
          {issue.resolved_at && <Info label="Resolved">{formatDate(issue.resolved_at)}</Info>}
          <Info label="Problem"><span className="font-normal text-slate-700">{issue.problem_description}</span></Info>
          {issue.notes && <Info label="Notes">{issue.notes}</Info>}
          {issue.resolution_note && <Info label="Resolution">{issue.resolution_note}</Info>}
        </div>
      </Card>

      {resolving && (
        <Card className="mb-4 p-4">
          <h3 className="mb-1 text-sm font-semibold text-slate-800">Resolve repair</h3>
          <p className="mb-3 text-xs text-slate-400">
            This deducts the {issue.lines.length} part{issue.lines.length === 1 ? "" : "s"} below from stock (recorded as an internal repair, not a sale) and returns the bike to {statusLabel(issue.prior_status)}. If any part is short of stock, nothing is deducted.
          </p>
          <input className={`${INPUT} mb-3 w-full`} placeholder="Resolution note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex items-center gap-2">
            <Button disabled={resolve.isPending} onClick={() => { setErr(null); resolve.mutate(); }}>{resolve.isPending ? "Resolving…" : "Confirm resolve & consume parts"}</Button>
            <Button variant="secondary" onClick={() => setResolving(false)}>Cancel</Button>
          </div>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
          <span className="text-sm font-semibold text-slate-700">Parts used</span>
        </div>
        {issue.lines.length === 0 ? (
          <div className="p-6 text-center text-sm text-slate-400">No parts recorded yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Part</th>
                <th className="px-4 py-2.5 font-medium">Source location</th>
                <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                {active && canManage && <th className="px-4 py-2.5" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {issue.lines.map((l) => (
                <tr key={l.id}>
                  <td className="px-4 py-3">{l.name}<span className="ml-2 font-mono text-xs text-slate-400">{l.sku}</span></td>
                  <td className="px-4 py-3 text-slate-600">{l.warehouse_name ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">{l.quantity}</td>
                  <td className="px-4 py-3">
                    {l.consumed
                      ? <span className="text-xs text-emerald-600">Consumed{l.consumed_at ? ` · ${formatDate(l.consumed_at)}` : ""}</span>
                      : <span className="flex items-center gap-2 text-xs text-slate-400">planned <StockBadge productId={l.product_id} warehouseId={l.warehouse_id} /></span>}
                  </td>
                  {active && canManage && (
                    <td className="px-4 py-3 text-right">
                      {!l.consumed && <button className="text-slate-400 hover:text-red-600" onClick={() => removeLine.mutate(l.id)}><Trash2 className="h-4 w-4" /></button>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {active && canManage && <AddLineForm issue={issue} onAdded={refresh} onErr={onErr} />}
      </Card>
    </div>
  );
}

function AddLineForm({ issue, onAdded, onErr }: { issue: BikeIssue; onAdded: () => void; onErr: (e: unknown) => void }) {
  const warehouses = useWarehouses();
  const [wh, setWh] = useState("");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<{ id: string; sku: string; name: string } | null>(null);
  const [qty, setQty] = useState(1);

  const partQ = useQuery({
    queryKey: ["bike-issue-addline-search", search],
    queryFn: () => catalogApi.products({ search: search.trim(), page: 1, page_size: 8 }),
    enabled: search.trim().length >= 2,
  });
  const add = useMutation({
    mutationFn: () => bikeIssuesApi.addLine(issue.id, { product_id: picked!.id, warehouse_id: wh, quantity: qty }),
    onSuccess: () => { setPicked(null); setSearch(""); setQty(1); onAdded(); },
    onError: onErr,
  });

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 bg-slate-50/60 px-4 py-3 text-sm">
      <Plus className="h-4 w-4 text-slate-400" />
      <select className={INPUT} value={wh} onChange={(e) => setWh(e.target.value)}>
        <option value="">Source location…</option>
        {warehouses.list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      {picked ? (
        <span className="flex items-center gap-2">
          <span className="text-slate-800">{picked.name} <span className="font-mono text-xs text-slate-400">{picked.sku}</span></span>
          {wh && <StockBadge productId={picked.id} warehouseId={wh} />}
          <button className="text-slate-400 hover:text-red-600" onClick={() => setPicked(null)}><Trash2 className="h-3.5 w-3.5" /></button>
        </span>
      ) : (
        <div className="relative">
          <input className={`${INPUT} w-52`} placeholder="Search part…" value={search} onChange={(e) => setSearch(e.target.value)} />
          {search.trim().length >= 2 && (
            <div className="absolute z-10 mt-1 max-h-40 w-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
              {(partQ.data?.items ?? []).map((p) => (
                <button key={p.id} className="flex w-full justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  onClick={() => { setPicked({ id: p.id, sku: p.sku, name: p.name }); setSearch(""); }}>
                  <span>{p.name}</span><span className="font-mono text-xs text-slate-400">{p.sku}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <input type="number" min={1} value={qty} className={`${INPUT} w-16 text-right`} onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
      <Button disabled={!wh || !picked || add.isPending} onClick={() => add.mutate()}>{add.isPending ? "Adding…" : "Add part"}</Button>
    </div>
  );
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div><div className="mt-0.5 text-slate-700">{children}</div></div>;
}
