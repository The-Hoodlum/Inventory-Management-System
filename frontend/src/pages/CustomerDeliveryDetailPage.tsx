// Customer / reseller delivery detail — header, lines, and actions: deliver (sale = mark
// handed over, no stock move; consignment = hold parts / consign bikes), settle an open
// consignment (per-item sold/returned qty, per-bike sold→invoice / returned), cancel (draft
// only), PDF. The note never moves stock itself — the server orchestrates via inventory.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  type CustomerDelivery,
  type CustomerDeliveryLine,
  type SettleCustomerDeliveryBody,
  customerDeliveryApi,
} from "@/lib/customerDelivery";
import { formatDate } from "@/lib/format";
import { salesApi } from "@/lib/sales";

const IN = "rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function CustomerDeliveryDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canDispatch = hasPermission("delivery_note.dispatch");
  const canReceive = hasPermission("delivery_note.receive");
  const canManage = hasPermission("sales.manage");   // may override a before-assembly block
  const [err, setErr] = useState<string | null>(null);
  const [settling, setSettling] = useState(false);

  const { data: cd, isLoading } = useQuery({ queryKey: ["customer-delivery", "one", id], queryFn: () => customerDeliveryApi.get(id), enabled: !!id });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["customer-delivery"] }); };
  const onErr = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Action failed.");
  const deliver = useMutation({ mutationFn: (override: boolean) => customerDeliveryApi.deliver(id, { override_unassembled: override }), onSuccess: refresh, onError: onErr });
  const cancel = useMutation({ mutationFn: () => customerDeliveryApi.cancel(id), onSuccess: refresh, onError: onErr });

  if (isLoading || !cd) return <div><PageHeader title="Delivery" /><div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div></div>;

  const isDraft = cd.status === "draft";
  const isOpenConsignment = cd.delivery_mode === "consignment" && (cd.status === "out_at_reseller" || cd.status === "partially_settled");
  // A SALE handover of a bike sold before assembly is blocked (not built yet) — a manager overrides.
  const unassembledChassis = cd.delivery_mode === "sale"
    ? cd.lines.filter((l) => l.line_kind === "motorcycle" && l.assembly_pending).map((l) => l.chassis_number ?? "—")
    : [];
  const blockedByAssembly = isDraft && unassembledChassis.length > 0;

  return (
    <div>
      <PageHeader
        title={cd.delivery_number}
        description={cd.delivery_mode === "sale"
          ? "Sale delivery — proof of a handover the sale already deducted."
          : "Consignment — goods held at the reseller until sold or returned."}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => navigate("/customer-deliveries")}>Back</Button>
            <Button variant="secondary" onClick={() => void customerDeliveryApi.downloadPdf(cd.id, cd.delivery_number)}>PDF</Button>
            {isDraft && canDispatch && !blockedByAssembly && <Button disabled={deliver.isPending} onClick={() => { setErr(null); deliver.mutate(false); }}>{deliver.isPending ? "Delivering…" : "Deliver"}</Button>}
            {isDraft && canDispatch && blockedByAssembly && canManage && <Button disabled={deliver.isPending} onClick={() => { setErr(null); deliver.mutate(true); }}>{deliver.isPending ? "Delivering…" : "Override & deliver"}</Button>}
            {isDraft && canDispatch && <Button variant="ghost" disabled={cancel.isPending} onClick={() => { setErr(null); cancel.mutate(); }}>Cancel</Button>}
            {isOpenConsignment && canReceive && !settling && <Button onClick={() => setSettling(true)}>Settle / return…</Button>}
          </div>
        }
      />
      {err && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      {blockedByAssembly && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
          <b>Not yet assembled:</b> {unassembledChassis.join(", ")}. Dispatch is blocked until the bike is
          assembled{canManage ? " — use “Override & deliver” to release it anyway." : ". A manager (sales.manage) can override."}
        </div>
      )}

      <Card className="mb-4 p-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm md:grid-cols-4">
          <Info label="Status"><StatusBadge status={cd.status} /></Info>
          <Info label="Mode">{cd.delivery_mode === "sale" ? "Sale" : "Consignment"}</Info>
          <Info label="Customer">{cd.customer_name ?? "—"}</Info>
          <Info label="Source">{cd.from_warehouse_name ?? "—"}</Info>
          {cd.invoice_number && <Info label="Invoice">{cd.invoice_number}</Info>}
          <Info label="Delivered">{cd.dispatched_at ? formatDate(cd.dispatched_at) : "—"}</Info>
          <Info label="Received by">{cd.received_by ?? "—"}</Info>
          {cd.remarks && <Info label="Remarks">{cd.remarks}</Info>}
        </div>
      </Card>

      {settling && isOpenConsignment ? (
        <SettleForm cd={cd} onClose={() => setSettling(false)} onDone={() => { setSettling(false); refresh(); }} />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Item / Chassis</th>
                <th className="px-4 py-2.5 font-medium">Kind</th>
                <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                {cd.delivery_mode === "consignment" && <th className="px-4 py-2.5 text-right font-medium">Settled</th>}
                {cd.delivery_mode === "consignment" && <th className="px-4 py-2.5 text-right font-medium">Returned</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {cd.lines.map((l) => (
                <tr key={l.id}>
                  <td className="px-4 py-3">{lineTitle(l)}</td>
                  <td className="px-4 py-3 text-slate-500">{l.line_kind === "motorcycle" ? "Bike" : "Item"}</td>
                  <td className="px-4 py-3 text-right font-mono">{l.qty}</td>
                  {cd.delivery_mode === "consignment" && <td className="px-4 py-3 text-right font-mono text-slate-600">{l.settled_qty || "—"}</td>}
                  {cd.delivery_mode === "consignment" && <td className="px-4 py-3 text-right font-mono text-slate-600">{l.returned_qty || "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function lineTitle(l: CustomerDeliveryLine) {
  if (l.line_kind === "motorcycle") {
    return (
      <span>
        <span className="font-mono text-[13px] text-slate-800">{l.chassis_number}</span>
        <span className="ml-2 text-xs text-slate-400">{l.model_name}</span>
        {l.assembly_pending && (
          <span className="ml-2 inline-flex items-center gap-1 rounded-pill bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-inset ring-orange-200">
            🟠 Awaiting assembly
          </span>
        )}
      </span>
    );
  }
  return <span>{l.name}<span className="ml-2 font-mono text-xs text-slate-400">{l.sku}</span></span>;
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div><div className="mt-0.5 text-slate-700">{children}</div></div>;
}

function SettleForm({ cd, onClose, onDone }: { cd: CustomerDelivery; onClose: () => void; onDone: () => void }) {
  // Only lines still out (not fully accounted) can be settled/returned.
  const openLines = cd.lines.filter((l) => l.settled_qty + l.returned_qty + 1e-9 < l.qty);
  const [parts, setParts] = useState<Record<string, { settled: number; returned: number }>>(
    Object.fromEntries(openLines.filter((l) => l.line_kind === "part").map((l) => [l.id, { settled: 0, returned: 0 }])),
  );
  const [bikes, setBikes] = useState<Record<string, { outcome: "sold" | "returned"; invoice_id: string }>>(
    Object.fromEntries(openLines.filter((l) => l.line_kind === "motorcycle").map((l) => [l.id, { outcome: "returned", invoice_id: "" }])),
  );
  const [err, setErr] = useState<string | null>(null);

  const hasBikes = openLines.some((l) => l.line_kind === "motorcycle");
  const invoicesQ = useQuery({ queryKey: ["cd-settle-invoices"], queryFn: () => salesApi.listInvoices(), enabled: hasBikes });

  const m = useMutation({
    mutationFn: () => {
      const body: SettleCustomerDeliveryBody = {
        part_lines: Object.entries(parts).map(([line_id, v]) => ({ line_id, settled_qty: v.settled, returned_qty: v.returned })),
        bike_lines: Object.entries(bikes).map(([line_id, v]) => ({ line_id, outcome: v.outcome, invoice_id: v.outcome === "sold" ? v.invoice_id : undefined })),
      };
      return customerDeliveryApi.settle(cd.id, body);
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not settle the consignment."),
  });

  if (openLines.length === 0) return <Card className="p-4 text-sm text-slate-500">Nothing left to settle. <Button variant="secondary" className="ml-2" onClick={onClose}>Close</Button></Card>;

  return (
    <Card className="p-4">
      <h3 className="mb-1 text-sm font-semibold text-slate-800">Settle / return consignment</h3>
      <p className="mb-3 text-xs text-slate-400">Sold quantities are deducted from stock; returned quantities release the hold. Sold bikes need a sales invoice.</p>
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="space-y-2">
        {openLines.map((l) => {
          const remaining = l.qty - l.settled_qty - l.returned_qty;
          return (
            <div key={l.id} className="flex flex-wrap items-center gap-3 border-b border-slate-100 py-2 text-sm">
              <span className="min-w-0 flex-1">{lineTitle(l)}<span className="ml-2 text-xs text-slate-400">({remaining} out)</span></span>
              {l.line_kind === "part" ? (
                <>
                  <label className="flex items-center gap-1 text-xs text-slate-500">Sold
                    <input type="number" min={0} max={remaining} value={parts[l.id]?.settled ?? 0}
                      onChange={(e) => setParts((p) => ({ ...p, [l.id]: { ...p[l.id], settled: clamp(Number(e.target.value), remaining) } }))} className={`${IN} w-16 text-right`} /></label>
                  <label className="flex items-center gap-1 text-xs text-slate-500">Returned
                    <input type="number" min={0} max={remaining} value={parts[l.id]?.returned ?? 0}
                      onChange={(e) => setParts((p) => ({ ...p, [l.id]: { ...p[l.id], returned: clamp(Number(e.target.value), remaining) } }))} className={`${IN} w-16 text-right`} /></label>
                </>
              ) : (
                <>
                  <select className={IN} value={bikes[l.id]?.outcome ?? "returned"} onChange={(e) => setBikes((b) => ({ ...b, [l.id]: { ...b[l.id], outcome: e.target.value as "sold" | "returned" } }))}>
                    <option value="returned">Returned unsold</option>
                    <option value="sold">Sold</option>
                  </select>
                  {bikes[l.id]?.outcome === "sold" && (
                    <select className={`${IN} w-56`} value={bikes[l.id]?.invoice_id ?? ""} onChange={(e) => setBikes((b) => ({ ...b, [l.id]: { ...b[l.id], invoice_id: e.target.value } }))}>
                      <option value="">Select the sales invoice…</option>
                      {(invoicesQ.data ?? []).map((inv) => <option key={inv.id} value={inv.id}>{inv.invoice_number} · {inv.customer_name ?? "—"}</option>)}
                    </select>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button disabled={m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Apply"}</Button>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
      </div>
    </Card>
  );
}

function clamp(v: number, max: number): number {
  return Math.min(max, Math.max(0, Number.isFinite(v) ? v : 0));
}
