// Delivery / dispatch notes — typed paper that documents a stock movement (Type 1:
// warehouse -> branch transfer). List + create (mixed bike + part lines from a source);
// dispatch/receive live on the detail page.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Truck } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { type CreateNoteBody, DISPATCH_TYPES, type DispatchNote, dispatchApi, dispatchStatusLabel } from "@/lib/dispatch";
import { formatDate } from "@/lib/format";
import { motorcyclesApi } from "@/lib/motorcycles";
import { useBranches, useWarehouses } from "@/lib/refdata";

const SELECT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function DeliveryNotesPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canDispatch = hasPermission("delivery_note.dispatch");
  const branches = useBranches();
  const [branch, setBranch] = useState("");
  const [status, setStatus] = useState("");
  const [showNew, setShowNew] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["dispatch", "list", branch, status],
    queryFn: () => dispatchApi.list({ branch_id: branch || undefined, status: status || undefined }),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader
        title="Delivery Notes"
        description="Paper that documents a stock movement. A warehouse → branch transfer sends stock in transit; the branch confirms on receipt."
        actions={canDispatch ? (
          <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New delivery note</Button>
        ) : undefined}
      />

      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <select className={SELECT} value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="">All branches</option>
            {branches.list.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <select className={SELECT} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {["draft", "in_transit", "partially_received", "received", "cancelled"].map((s) => (
              <option key={s} value={s}>{dispatchStatusLabel(s)}</option>
            ))}
          </select>
          {isFetching && <Spinner />}
        </div>
      </Card>

      <Card className="overflow-hidden">
        {!data ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : data.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <Truck className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            No delivery notes yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Note #</th>
                <th className="px-4 py-2.5 font-medium">From → To</th>
                <th className="px-4 py-2.5 font-medium">Lines</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((n) => (
                <tr key={n.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/delivery-notes/${n.id}`)}>
                  <td className="px-4 py-3 font-mono text-[13px] font-medium">{n.note_number}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {(n.from_branch_name ?? n.from_warehouse_name)} → {(n.to_branch_name ?? n.to_warehouse_name)}
                  </td>
                  <td className="px-4 py-3 text-slate-500">{lineSummary(n)}</td>
                  <td className="px-4 py-3"><StatusBadge status={n.status} /></td>
                  <td className="px-4 py-3 text-slate-500">{formatDate(n.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {showNew && <NewNoteModal onClose={() => setShowNew(false)} onCreated={(id) => navigate(`/delivery-notes/${id}`)} />}
    </div>
  );
}

function lineSummary(n: DispatchNote): string {
  const bikes = n.lines.filter((l) => l.line_kind === "motorcycle").length;
  const parts = n.lines.filter((l) => l.line_kind === "part").length;
  return [bikes ? `${bikes} bike${bikes === 1 ? "" : "s"}` : null, parts ? `${parts} part${parts === 1 ? "" : "s"}` : null]
    .filter(Boolean).join(", ") || "—";
}

const INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

interface PartRow { product_id: string; sku: string; name: string; qty: number }
interface BikeRow { unit_id: string; chassis: string; model: string }

function NewNoteModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const warehouses = useWarehouses();
  const branches = useBranches();
  const [type, setType] = useState<CreateNoteBody["dispatch_type"]>("warehouse_branch_transfer");
  const [fromWh, setFromWh] = useState("");
  const [toWh, setToWh] = useState("");
  const [remarks, setRemarks] = useState("");
  const [partSearch, setPartSearch] = useState("");
  const [bikeSearch, setBikeSearch] = useState("");
  const [parts, setParts] = useState<PartRow[]>([]);
  const [bikes, setBikes] = useState<BikeRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const whLabel = (w: { name: string; branch_id: string | null }) => {
    const b = w.branch_id ? branches.map.get(w.branch_id) : undefined;
    return b ? `${b.name} · ${w.name}` : w.name;
  };
  const fromWarehouse = warehouses.list.find((w) => w.id === fromWh);

  const partQ = useQuery({
    queryKey: ["dn-part-search", partSearch],
    queryFn: () => catalogApi.products({ search: partSearch.trim(), page: 1, page_size: 8 }),
    enabled: partSearch.trim().length >= 2,
  });
  const bikeQ = useQuery({
    queryKey: ["dn-bike-search", bikeSearch, fromWh],
    queryFn: () => motorcyclesApi.listUnits({ search: bikeSearch.trim(), branch_id: fromWarehouse?.branch_id ?? undefined, sold: false, page_size: 8 }),
    enabled: bikeSearch.trim().length >= 2 && !!fromWh,
  });

  const partIds = new Set(parts.map((p) => p.product_id));
  const bikeIds = new Set(bikes.map((b) => b.unit_id));

  const create = useMutation({
    mutationFn: () =>
      dispatchApi.create({
        dispatch_type: type, from_warehouse_id: fromWh, to_warehouse_id: toWh,
        remarks: remarks || undefined,
        part_lines: parts.map((p) => ({ product_id: p.product_id, qty: p.qty })),
        bike_lines: bikes.map((b) => ({ unit_id: b.unit_id })),
      }),
    onSuccess: (n) => { void qc.invalidateQueries({ queryKey: ["dispatch"] }); onCreated(n.id); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the note."),
  });

  const valid = fromWh && toWh && fromWh !== toWh && (parts.length > 0 || bikes.length > 0);

  return (
    <Modal title="New delivery note" size="xl" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>
          {create.isPending ? "Creating…" : "Create note"}
        </Button>
      </>
    }>
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="grid grid-cols-3 gap-3">
          <Field label="Type">
            <select className={INPUT} value={type} onChange={(e) => setType(e.target.value as CreateNoteBody["dispatch_type"])}>
              {DISPATCH_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="From (source location) *">
            <select className={INPUT} value={fromWh} onChange={(e) => { setFromWh(e.target.value); setBikes([]); }}>
              <option value="">Select…</option>
              {warehouses.list.map((w) => <option key={w.id} value={w.id}>{whLabel(w)}</option>)}
            </select>
          </Field>
          <Field label="To (destination) *">
            <select className={INPUT} value={toWh} onChange={(e) => setToWh(e.target.value)}>
              <option value="">Select…</option>
              {warehouses.list.filter((w) => w.id !== fromWh).map((w) => <option key={w.id} value={w.id}>{whLabel(w)}</option>)}
            </select>
          </Field>
        </div>

        {/* Bike lines */}
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Motorcycles (by chassis, from the source)</div>
          {!fromWh ? (
            <p className="text-xs text-slate-400">Pick a source location first.</p>
          ) : (
            <input className={INPUT} placeholder="Search chassis / engine / registration" value={bikeSearch} onChange={(e) => setBikeSearch(e.target.value)} />
          )}
          {bikeSearch.trim().length >= 2 && fromWh && (
            <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-slate-200">
              {(bikeQ.data?.items ?? []).filter((u) => !bikeIds.has(u.id)).map((u) => (
                <button key={u.id} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  onClick={() => { setBikes((b) => [...b, { unit_id: u.id, chassis: u.chassis_number, model: u.model_name ?? "" }]); setBikeSearch(""); }}>
                  <span className="font-mono text-[13px]">{u.chassis_number}</span>
                  <span className="text-xs text-slate-500">{u.model_name} · {dispatchStatusLabel(u.status)}</span>
                </button>
              ))}
              {(bikeQ.data?.items ?? []).length === 0 && <div className="p-2 text-xs text-slate-400">No matching units at the source.</div>}
            </div>
          )}
          {bikes.map((b, i) => (
            <div key={b.unit_id} className="mt-1 flex items-center gap-2 text-sm">
              <span className="font-mono text-[13px] text-slate-800">{b.chassis}</span>
              <span className="text-xs text-slate-500">{b.model}</span>
              <button className="ml-auto text-slate-400 hover:text-red-600" onClick={() => setBikes((bs) => bs.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>

        {/* Part lines */}
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Spare parts (by quantity)</div>
          <input className={INPUT} placeholder="Search product (name / SKU)" value={partSearch} onChange={(e) => setPartSearch(e.target.value)} />
          {partSearch.trim().length >= 2 && (
            <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-slate-200">
              {(partQ.data?.items ?? []).filter((p) => !partIds.has(p.id)).map((p) => (
                <button key={p.id} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  onClick={() => { setParts((ps) => [...ps, { product_id: p.id, sku: p.sku, name: p.name, qty: 1 }]); setPartSearch(""); }}>
                  <span>{p.name}</span><span className="font-mono text-xs text-slate-400">{p.sku}</span>
                </button>
              ))}
            </div>
          )}
          {parts.map((p, i) => (
            <div key={p.product_id} className="mt-1 flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-slate-800">{p.name} <span className="font-mono text-xs text-slate-400">{p.sku}</span></span>
              <input type="number" min={1} value={p.qty} className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-right text-sm"
                onChange={(e) => setParts((ps) => ps.map((x, j) => j === i ? { ...x, qty: Math.max(1, Number(e.target.value)) } : x))} />
              <button className="text-slate-400 hover:text-red-600" onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>

        <Field label="Remarks">
          <input className={INPUT} value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Optional note" />
        </Field>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">{label}</span>{children}</label>;
}
