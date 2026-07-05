// Internal issuance / handover (out-and-back loan) — list what's currently out (with
// overdue), and create a new handover (bike + item lines from a source; mark consumables).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, HandHelping, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { type CreateIssuanceBody, type Issuance, issuanceApi } from "@/lib/issuance";
import { motorcyclesApi } from "@/lib/motorcycles";
import { useWarehouses } from "@/lib/refdata";

const INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function IssuancesPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canIssue = hasPermission("delivery_note.dispatch");
  const [openOnly, setOpenOnly] = useState(true);
  const [showNew, setShowNew] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["issuance", "list", openOnly],
    queryFn: () => issuanceApi.list({ open: openOnly }),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader
        title="Issuances / Handovers"
        description="Issue a bike or items on loan for an event or test, then get them back. On-loan stock is not sellable but stays in company ownership — it is never deducted."
        actions={canIssue ? <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New issuance</Button> : undefined}
      />

      <Card className="mb-4 p-4">
        <label className="flex w-fit items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
          Currently out on loan only
          {isFetching && <Spinner />}
        </label>
      </Card>

      <Card className="overflow-hidden">
        {!data ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : data.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <HandHelping className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            Nothing on loan.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Issuance #</th>
                <th className="px-4 py-2.5 font-medium">Requestor / dept</th>
                <th className="px-4 py-2.5 font-medium">Lines</th>
                <th className="px-4 py-2.5 font-medium">Due back</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((i) => (
                <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/issuances/${i.id}`)}>
                  <td className="px-4 py-3 font-mono text-[13px] font-medium">{i.issuance_number}</td>
                  <td className="px-4 py-3 text-slate-600">{[i.requestor, i.department].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{summary(i)}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {i.expected_return_date ?? "—"}
                    {i.overdue && <span className="ml-1 inline-flex items-center gap-0.5 text-xs font-medium text-red-600"><AlertTriangle className="h-3 w-3" /> overdue</span>}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={i.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {showNew && <NewIssuanceModal onClose={() => setShowNew(false)} onCreated={(id) => navigate(`/issuances/${id}`)} />}
    </div>
  );
}

function summary(i: Issuance): string {
  const bikes = i.lines.filter((l) => l.line_kind === "motorcycle").length;
  const parts = i.lines.filter((l) => l.line_kind === "part").length;
  return [bikes ? `${bikes} bike${bikes === 1 ? "" : "s"}` : null, parts ? `${parts} item${parts === 1 ? "" : "s"}` : null].filter(Boolean).join(", ") || "—";
}

interface PartRow { product_id: string; sku: string; name: string; qty: number; consumable: boolean }
interface BikeRow { unit_id: string; chassis: string; model: string; odometer_out: string; fuel_out: string; accessories: string }

function NewIssuanceModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const warehouses = useWarehouses();
  const [wh, setWh] = useState("");
  const [requestor, setRequestor] = useState("");
  const [department, setDepartment] = useState("");
  const [purpose, setPurpose] = useState("");
  const [expected, setExpected] = useState("");
  const [partSearch, setPartSearch] = useState("");
  const [bikeSearch, setBikeSearch] = useState("");
  const [parts, setParts] = useState<PartRow[]>([]);
  const [bikes, setBikes] = useState<BikeRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const whObj = warehouses.list.find((w) => w.id === wh);
  const partQ = useQuery({
    queryKey: ["iss-part-search", partSearch],
    queryFn: () => catalogApi.products({ search: partSearch.trim(), page: 1, page_size: 8 }),
    enabled: partSearch.trim().length >= 2,
  });
  const bikeQ = useQuery({
    queryKey: ["iss-bike-search", bikeSearch, wh],
    queryFn: () => motorcyclesApi.listUnits({ search: bikeSearch.trim(), branch_id: whObj?.branch_id ?? undefined, sold: false, page_size: 8 }),
    enabled: bikeSearch.trim().length >= 2 && !!wh,
  });
  const partIds = new Set(parts.map((p) => p.product_id));
  const bikeIds = new Set(bikes.map((b) => b.unit_id));

  const create = useMutation({
    mutationFn: () => {
      const body: CreateIssuanceBody = {
        warehouse_id: wh,
        requestor: requestor || undefined, department: department || undefined,
        purpose: purpose || undefined, expected_return_date: expected || undefined,
        part_lines: parts.map((p) => ({ product_id: p.product_id, qty: p.qty, consumable: p.consumable, returnable: !p.consumable })),
        bike_lines: bikes.map((b) => ({ unit_id: b.unit_id, odometer_out: b.odometer_out ? Number(b.odometer_out) : undefined, fuel_out: b.fuel_out || undefined, accessories: b.accessories || undefined })),
      };
      return issuanceApi.create(body);
    },
    onSuccess: (i) => { void qc.invalidateQueries({ queryKey: ["issuance"] }); onCreated(i.id); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the issuance."),
  });

  const valid = wh && (parts.length > 0 || bikes.length > 0);

  return (
    <Modal title="New issuance / handover" size="xl" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>{create.isPending ? "Creating…" : "Create"}</Button>
      </>
    }>
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Source location *">
            <select className={INPUT} value={wh} onChange={(e) => { setWh(e.target.value); setBikes([]); }}>
              <option value="">Select…</option>
              {warehouses.list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
          <Field label="Expected return date"><input type="date" className={INPUT} value={expected} onChange={(e) => setExpected(e.target.value)} /></Field>
          <Field label="Requestor"><input className={INPUT} value={requestor} onChange={(e) => setRequestor(e.target.value)} placeholder="Person" /></Field>
          <Field label="Department"><input className={INPUT} value={department} onChange={(e) => setDepartment(e.target.value)} /></Field>
          <Field label="Purpose / activity"><input className={INPUT} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Event, test, display…" /></Field>
        </div>

        {/* Bikes */}
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Motorcycles (out on loan, by chassis)</div>
          {!wh ? <p className="text-xs text-slate-400">Pick a source location first.</p> : (
            <input className={INPUT} placeholder="Search chassis / engine" value={bikeSearch} onChange={(e) => setBikeSearch(e.target.value)} />
          )}
          {bikeSearch.trim().length >= 2 && wh && (
            <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200">
              {(bikeQ.data?.items ?? []).filter((u) => !bikeIds.has(u.id)).map((u) => (
                <button key={u.id} className="flex w-full justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  onClick={() => { setBikes((b) => [...b, { unit_id: u.id, chassis: u.chassis_number, model: u.model_name ?? "", odometer_out: "", fuel_out: "", accessories: "" }]); setBikeSearch(""); }}>
                  <span className="font-mono text-[13px]">{u.chassis_number}</span><span className="text-xs text-slate-500">{u.model_name}</span>
                </button>
              ))}
            </div>
          )}
          {bikes.map((b, i) => (
            <div key={b.unit_id} className="mt-1 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono text-[13px] text-slate-800">{b.chassis}</span>
              <input className="w-24 rounded border border-slate-300 px-2 py-1 text-xs" placeholder="Odometer" value={b.odometer_out} onChange={(e) => setBikes((bs) => bs.map((x, j) => j === i ? { ...x, odometer_out: e.target.value } : x))} />
              <input className="w-20 rounded border border-slate-300 px-2 py-1 text-xs" placeholder="Fuel" value={b.fuel_out} onChange={(e) => setBikes((bs) => bs.map((x, j) => j === i ? { ...x, fuel_out: e.target.value } : x))} />
              <input className="w-32 rounded border border-slate-300 px-2 py-1 text-xs" placeholder="Accessories" value={b.accessories} onChange={(e) => setBikes((bs) => bs.map((x, j) => j === i ? { ...x, accessories: e.target.value } : x))} />
              <button className="ml-auto text-slate-400 hover:text-red-600" onClick={() => setBikes((bs) => bs.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>

        {/* Items */}
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Items (held on loan; tick “consumable” for giveaways)</div>
          <input className={INPUT} placeholder="Search item (name / SKU)" value={partSearch} onChange={(e) => setPartSearch(e.target.value)} />
          {partSearch.trim().length >= 2 && (
            <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200">
              {(partQ.data?.items ?? []).filter((p) => !partIds.has(p.id)).map((p) => (
                <button key={p.id} className="flex w-full justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  onClick={() => { setParts((ps) => [...ps, { product_id: p.id, sku: p.sku, name: p.name, qty: 1, consumable: false }]); setPartSearch(""); }}>
                  <span>{p.name}</span><span className="font-mono text-xs text-slate-400">{p.sku}</span>
                </button>
              ))}
            </div>
          )}
          {parts.map((p, i) => (
            <div key={p.product_id} className="mt-1 flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-slate-800">{p.name} <span className="font-mono text-xs text-slate-400">{p.sku}</span></span>
              <input type="number" min={1} value={p.qty} className="w-16 rounded border border-slate-300 px-2 py-1 text-right text-sm" onChange={(e) => setParts((ps) => ps.map((x, j) => j === i ? { ...x, qty: Math.max(1, Number(e.target.value)) } : x))} />
              <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={p.consumable} onChange={(e) => setParts((ps) => ps.map((x, j) => j === i ? { ...x, consumable: e.target.checked } : x))} /> consumable</label>
              <button className="text-slate-400 hover:text-red-600" onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">{label}</span>{children}</label>;
}
