// Branch -> customer/reseller delivery (Type 3) — list deliveries and create a new one in
// either mode: SALE (pick a paid/issued invoice; the note is just proof, no re-deduction) or
// CONSIGNMENT (goods held at the reseller: pick a customer + item/bike lines).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackageCheck, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import {
  type CreateCustomerDeliveryBody,
  type CustomerDelivery,
  type CustomerDeliveryMode,
  customerDeliveryApi,
} from "@/lib/customerDelivery";
import { customersApi } from "@/lib/customers";
import { motorcyclesApi } from "@/lib/motorcycles";
import { useWarehouses } from "@/lib/refdata";
import { salesApi } from "@/lib/sales";

const INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function CustomerDeliveriesPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canDispatch = hasPermission("delivery_note.dispatch");
  const [showNew, setShowNew] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["customer-delivery", "list"],
    queryFn: () => customerDeliveryApi.list(),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader
        title="Customer / Reseller Deliveries"
        description="Deliver goods to a customer or reseller. A sale delivery is proof of a handover the sale already deducted; a consignment holds stock at the reseller until it is sold or returned. The note never moves stock on its own."
        actions={canDispatch ? <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New delivery</Button> : undefined}
      />

      <Card className="overflow-hidden">
        {isFetching && !data ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : !data || data.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <PackageCheck className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            No customer deliveries yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Delivery #</th>
                <th className="px-4 py-2.5 font-medium">Mode</th>
                <th className="px-4 py-2.5 font-medium">Customer</th>
                <th className="px-4 py-2.5 font-medium">Lines</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((d) => (
                <tr key={d.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/customer-deliveries/${d.id}`)}>
                  <td className="px-4 py-3 font-mono text-[13px] font-medium">{d.delivery_number}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${d.delivery_mode === "sale" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                      {d.delivery_mode === "sale" ? "Sale" : "Consignment"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{d.customer_name ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{summary(d)}</td>
                  <td className="px-4 py-3"><StatusBadge status={d.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {showNew && <NewDeliveryModal onClose={() => setShowNew(false)} onCreated={(id) => navigate(`/customer-deliveries/${id}`)} />}
    </div>
  );
}

function summary(d: CustomerDelivery): string {
  const bikes = d.lines.filter((l) => l.line_kind === "motorcycle").length;
  const parts = d.lines.filter((l) => l.line_kind === "part").length;
  return [bikes ? `${bikes} bike${bikes === 1 ? "" : "s"}` : null, parts ? `${parts} item${parts === 1 ? "" : "s"}` : null].filter(Boolean).join(", ") || "—";
}

interface PartRow { product_id: string; sku: string; name: string; qty: number }
interface BikeRow { unit_id: string; chassis: string; model: string }

function NewDeliveryModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const warehouses = useWarehouses();
  const [mode, setMode] = useState<CustomerDeliveryMode>("consignment");
  const [wh, setWh] = useState("");
  const [remarks, setRemarks] = useState("");
  const [err, setErr] = useState<string | null>(null);

  // sale mode
  const [invoiceId, setInvoiceId] = useState("");
  const invoicesQ = useQuery({ queryKey: ["cd-invoices"], queryFn: () => salesApi.listInvoices(), enabled: mode === "sale" });

  // consignment mode
  const [customerId, setCustomerId] = useState("");
  const customersQ = useQuery({ queryKey: ["cd-customers"], queryFn: () => customersApi.list(), enabled: mode === "consignment" });
  const [partSearch, setPartSearch] = useState("");
  const [bikeSearch, setBikeSearch] = useState("");
  const [parts, setParts] = useState<PartRow[]>([]);
  const [bikes, setBikes] = useState<BikeRow[]>([]);

  const whObj = warehouses.list.find((w) => w.id === wh);
  const partQ = useQuery({
    queryKey: ["cd-part-search", partSearch],
    queryFn: () => catalogApi.products({ search: partSearch.trim(), page: 1, page_size: 8 }),
    enabled: mode === "consignment" && partSearch.trim().length >= 2,
  });
  const bikeQ = useQuery({
    queryKey: ["cd-bike-search", bikeSearch, wh],
    queryFn: () => motorcyclesApi.listUnits({ search: bikeSearch.trim(), branch_id: whObj?.branch_id ?? undefined, sold: false, page_size: 8 }),
    enabled: mode === "consignment" && bikeSearch.trim().length >= 2 && !!wh,
  });
  const partIds = new Set(parts.map((p) => p.product_id));
  const bikeIds = new Set(bikes.map((b) => b.unit_id));

  const create = useMutation({
    mutationFn: () => {
      const body: CreateCustomerDeliveryBody =
        mode === "sale"
          ? { delivery_mode: "sale", from_warehouse_id: wh, invoice_id: invoiceId, remarks: remarks || undefined }
          : {
              delivery_mode: "consignment", from_warehouse_id: wh, customer_id: customerId, remarks: remarks || undefined,
              part_lines: parts.map((p) => ({ product_id: p.product_id, qty: p.qty })),
              bike_lines: bikes.map((b) => ({ unit_id: b.unit_id })),
            };
      return customerDeliveryApi.create(body);
    },
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["customer-delivery"] }); onCreated(d.id); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the delivery."),
  });

  const valid = mode === "sale" ? !!(wh && invoiceId) : !!(wh && customerId && (parts.length > 0 || bikes.length > 0));

  return (
    <Modal title="New customer / reseller delivery" size="xl" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>{create.isPending ? "Creating…" : "Create"}</Button>
      </>
    }>
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        {/* Mode toggle */}
        <div className="flex gap-2">
          {(["sale", "consignment"] as CustomerDeliveryMode[]).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={`flex-1 rounded-lg border px-3 py-2 text-left text-sm ${mode === m ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:bg-slate-50"}`}>
              <div className="font-medium text-slate-800">{m === "sale" ? "Sale" : "Consignment"}</div>
              <div className="text-xs text-slate-500">{m === "sale" ? "Proof of a handover the sale already deducted." : "Goods held at the reseller; settled when sold."}</div>
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Source location *">
            <select className={INPUT} value={wh} onChange={(e) => { setWh(e.target.value); setBikes([]); }}>
              <option value="">Select…</option>
              {warehouses.list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
          {mode === "sale" ? (
            <Field label="Invoice *">
              <select className={INPUT} value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)}>
                <option value="">Select an invoice…</option>
                {(invoicesQ.data ?? []).map((inv) => (
                  <option key={inv.id} value={inv.id}>{inv.invoice_number} · {inv.customer_name ?? "—"}</option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label="Customer / reseller *">
              <select className={INPUT} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="">Select a customer…</option>
                {(customersQ.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          )}
        </div>

        {mode === "sale" ? (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
            The delivery lines are taken from the invoice (parts + any linked bikes). Delivering it records the handover only — it does <strong>not</strong> deduct stock again.
          </p>
        ) : (
          <>
            {/* Bikes */}
            <div>
              <div className="mb-1 text-sm font-medium text-slate-700">Motorcycles (consigned, by chassis)</div>
              {!wh ? <p className="text-xs text-slate-400">Pick a source location first.</p> : (
                <input className={INPUT} placeholder="Search chassis / engine" value={bikeSearch} onChange={(e) => setBikeSearch(e.target.value)} />
              )}
              {bikeSearch.trim().length >= 2 && wh && (
                <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200">
                  {(bikeQ.data?.items ?? []).filter((u) => !bikeIds.has(u.id)).map((u) => (
                    <button key={u.id} className="flex w-full justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                      onClick={() => { setBikes((b) => [...b, { unit_id: u.id, chassis: u.chassis_number, model: u.model_name ?? "" }]); setBikeSearch(""); }}>
                      <span className="font-mono text-[13px]">{u.chassis_number}</span><span className="text-xs text-slate-500">{u.model_name}</span>
                    </button>
                  ))}
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

            {/* Items */}
            <div>
              <div className="mb-1 text-sm font-medium text-slate-700">Items (held at the reseller)</div>
              <input className={INPUT} placeholder="Search item (name / SKU)" value={partSearch} onChange={(e) => setPartSearch(e.target.value)} />
              {partSearch.trim().length >= 2 && (
                <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200">
                  {(partQ.data?.items ?? []).filter((p) => !partIds.has(p.id)).map((p) => (
                    <button key={p.id} className="flex w-full justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                      onClick={() => { setParts((ps) => [...ps, { product_id: p.id, sku: p.sku, name: p.name, qty: 1 }]); setPartSearch(""); }}>
                      <span>{p.name}</span><span className="font-mono text-xs text-slate-400">{p.sku}</span>
                    </button>
                  ))}
                </div>
              )}
              {parts.map((p, i) => (
                <div key={p.product_id} className="mt-1 flex items-center gap-2 text-sm">
                  <span className="min-w-0 flex-1 truncate text-slate-800">{p.name} <span className="font-mono text-xs text-slate-400">{p.sku}</span></span>
                  <input type="number" min={1} value={p.qty} className="w-16 rounded border border-slate-300 px-2 py-1 text-right text-sm" onChange={(e) => setParts((ps) => ps.map((x, j) => j === i ? { ...x, qty: Math.max(1, Number(e.target.value)) } : x))} />
                  <button className="text-slate-400 hover:text-red-600" onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          </>
        )}

        <Field label="Remarks"><input className={INPUT} value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Optional note" /></Field>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">{label}</span>{children}</label>;
}
