import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { PaymentModal } from "@/components/PaymentModal";
import { SellBikeModal } from "@/components/SellBikeModal";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { useCustomers } from "@/lib/customers";
import { formatDate, formatMoney, formatNumber, titleCase } from "@/lib/format";
import { useBranches, useWarehouses } from "@/lib/refdata";
import type { Invoice } from "@/lib/sales";
import { RETURN_REASONS, salesApi } from "@/lib/sales";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const TH = "px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-slate-500";
const THR = "px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-slate-500";

type Tab = "orders" | "quotations" | "invoices" | "returns" | "credit_notes";
const TABS: Tab[] = ["orders", "quotations", "invoices", "returns", "credit_notes"];

export default function SalesPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canOrder = hasPermission("sales.order");
  const canQuote = hasPermission("sales.quote");
  const canReturn = hasPermission("sales.return");
  const canVoid = hasPermission("sales.manage");
  const canSellBike = hasPermission("motorcycle.manage");
  const [tab, setTab] = useState<Tab>("orders");
  const [showNew, setShowNew] = useState(false);
  const [showSellBike, setShowSellBike] = useState(false);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [payInvoice, setPayInvoice] = useState<string | null>(null);
  const [voidInvoice, setVoidInvoice] = useState<Invoice | null>(null);
  const [returnInvoice, setReturnInvoice] = useState<Invoice | null>(null);

  const orders = useQuery({ queryKey: ["sales", "orders"], queryFn: () => salesApi.listOrders(), enabled: tab === "orders" });
  const quotes = useQuery({ queryKey: ["sales", "quotes"], queryFn: () => salesApi.listQuotations(), enabled: tab === "quotations" });
  const invoices = useQuery({ queryKey: ["sales", "invoices"], queryFn: () => salesApi.listInvoices(), enabled: tab === "invoices" });
  const returns = useQuery({ queryKey: ["sales", "returns"], queryFn: () => salesApi.listReturns(), enabled: tab === "returns" });
  const creditNotes = useQuery({ queryKey: ["sales", "credit_notes"], queryFn: () => salesApi.listCreditNotes(), enabled: tab === "credit_notes" });

  return (
    <div>
      <PageHeader
        title="Sales"
        description="Quotations, sales orders, deliveries and invoices — fully linked and traceable."
        actions={
          <div className="flex items-center gap-2">
            {canSellBike && <Button variant="secondary" onClick={() => setShowSellBike(true)}>Sell a bike</Button>}
            {canQuote && <Button variant="secondary" onClick={() => navigate("/sales/quotations/new")}>New quotation</Button>}
            {canOrder && <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New order</Button>}
          </div>
        }
      />
      {showSellBike && <SellBikeModal onClose={() => setShowSellBike(false)} onSold={() => { void qc.invalidateQueries({ queryKey: ["sales"] }); }} />}

      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={"rounded-t-lg px-4 py-2 text-sm font-medium transition " +
              (tab === t ? "border-b-2 border-brand-600 text-brand-700" : "text-slate-500 hover:text-slate-700")}>
            {titleCase(t.replace("_", " "))}
          </button>
        ))}
      </div>

      {tab === "orders" && (
        <DocTable q={orders} cols={["Order #", "Customer", "Location", "Status", "Total", "Date"]}
          row={(o) => (
            <tr key={o.id} onClick={() => setOrderId(o.id)} className="cursor-pointer hover:bg-slate-50">
              <td className="px-4 py-3 font-mono text-[13px] font-medium">{o.so_number}</td>
              <td className="px-4 py-3 text-slate-600">{o.customer_name ?? "—"}</td>
              <td className="px-4 py-3 text-slate-600">{o.location_name ?? "—"}</td>
              <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
              <td className="px-4 py-3 text-right font-mono">{formatMoney(o.grand_total)}</td>
              <td className="px-4 py-3 text-slate-500">{formatDate(o.created_at)}</td>
            </tr>
          )} />
      )}
      {tab === "quotations" && (
        <DocTable q={quotes} cols={["Quote #", "Customer", "Status", "USD total", "ZMW total", "Valid until", "Date"]}
          row={(o) => (
            <tr key={o.id} className="hover:bg-slate-50">
              <td className="px-4 py-3 font-mono text-[13px] font-medium">
                {o.quote_number}
                <div className="text-2xs font-normal text-slate-400">@ {formatNumber(o.fx_rate)}</div>
              </td>
              <td className="px-4 py-3 text-slate-600">{o.customer_name ?? "—"}</td>
              <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
              <td className="px-4 py-3 text-right font-mono">{formatMoney(o.grand_total)}</td>
              <td className="px-4 py-3 text-right font-mono font-medium">{formatMoney(o.grand_total_zmw, "ZMW")}</td>
              <td className="px-4 py-3 text-slate-500">{o.valid_until ?? "—"}</td>
              <td className="px-4 py-3 text-slate-500">{formatDate(o.created_at)}</td>
            </tr>
          )} />
      )}
      {tab === "invoices" && (
        <DocTable q={invoices} cols={["Invoice #", "Customer", "Status", "USD total", "ZMW payable", "ZMW balance", ""]}
          row={(o) => (
            <tr key={o.id} className={"hover:bg-slate-50 " + (o.status === "voided" ? "opacity-60" : "")}>
              <td className="px-4 py-3 font-mono text-[13px] font-medium">
                {o.invoice_number}
                <div className="text-2xs font-normal text-slate-400">@ {formatNumber(o.fx_rate)}</div>
              </td>
              <td className="px-4 py-3 text-slate-600">{o.customer_name ?? "—"}</td>
              <td className="px-4 py-3">
                <StatusBadge status={o.status} />
                {o.status === "voided" && o.void_reason && (
                  <div className="text-2xs text-slate-400" title={o.void_reason}>voided: {o.void_reason.slice(0, 28)}</div>
                )}
              </td>
              <td className="px-4 py-3 text-right font-mono">{formatMoney(o.grand_total)}</td>
              <td className="px-4 py-3 text-right font-mono font-medium">{formatMoney(o.grand_total_zmw, "ZMW")}</td>
              <td className="px-4 py-3 text-right font-mono">{formatMoney(o.balance, "ZMW")}</td>
              <td className="px-4 py-3 text-right">
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => void salesApi.downloadInvoicePdf(o.id, o.invoice_number)}>PDF</Button>
                  {o.status !== "voided" && canReturn && o.lines.length > 0 && (
                    <Button variant="ghost" onClick={() => setReturnInvoice(o)}>Return</Button>
                  )}
                  {o.status !== "voided" && o.balance > 0 && hasPermission("sales.payment") && (
                    <Button variant="secondary" onClick={() => setPayInvoice(o.id)}>Record payment</Button>
                  )}
                  {o.status !== "voided" && canVoid && (
                    <Button variant="ghost" onClick={() => setVoidInvoice(o)}>Void</Button>
                  )}
                </div>
              </td>
            </tr>
          )} />
      )}
      {tab === "returns" && (
        <DocTable q={returns} cols={["Return #", "Customer", "Reason", "Status", "Location", "Date"]}
          row={(o) => (
            <tr key={o.id} className="hover:bg-slate-50">
              <td className="px-4 py-3 font-mono text-[13px] font-medium">{o.return_number}</td>
              <td className="px-4 py-3 text-slate-600">{o.customer_name ?? "—"}</td>
              <td className="px-4 py-3 text-slate-600">{titleCase(o.reason.replace("_", " "))}</td>
              <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
              <td className="px-4 py-3 text-slate-600">{o.location_name ?? "—"}</td>
              <td className="px-4 py-3 text-slate-500">{formatDate(o.created_at)}</td>
            </tr>
          )} />
      )}
      {tab === "credit_notes" && (
        <DocTable q={creditNotes} cols={["Credit note #", "Customer", "Invoice", "Status", "Total", ""]}
          row={(o) => <CreditNoteRow key={o.id} cn={o} canReturn={canReturn} />} />
      )}

      {showNew && <NewOrderModal onClose={() => setShowNew(false)} />}
      {orderId && <OrderDetailModal orderId={orderId} onClose={() => setOrderId(null)} onPay={setPayInvoice} />}
      {payInvoice && <PaymentModal invoiceId={payInvoice} onClose={() => setPayInvoice(null)} />}
      {voidInvoice && <VoidInvoiceModal invoice={voidInvoice} onClose={() => setVoidInvoice(null)} />}
      {returnInvoice && <ReturnModal invoice={returnInvoice} onClose={() => setReturnInvoice(null)} />}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function DocTable({ q, cols, row }: { q: any; cols: string[]; row: (o: any) => React.ReactNode }) {
  if (q.isLoading) return <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>;
  const items = q.data ?? [];
  if (items.length === 0) return <Card className="p-10 text-center text-sm text-slate-400">Nothing here yet.</Card>;
  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr className="border-b border-slate-200">
            {cols.map((c, i) => <th key={c || i} className={i >= 3 ? THR : TH}>{c}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-slate-100">{items.map(row)}</tbody>
        </table>
      </div>
    </Card>
  );
}

function NewOrderModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const customers = useCustomers();
  const warehouses = useWarehouses();
  const branches = useBranches();
  const locLabel = (w: { name: string; branch_id: string | null }) => {
    const b = w.branch_id ? branches.map.get(w.branch_id) : undefined;
    return b ? `${b.name} · ${w.name}` : w.name;
  };
  const [customerId, setCustomerId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<{ product_id: string; sku: string; name: string; qty: string; unit_price: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const term = search.trim();
  const searchQ = useQuery({
    queryKey: ["product-search", term], enabled: term.length >= 2,
    queryFn: () => catalogApi.products({ search: term, page: 1, page_size: 8 }),
    placeholderData: (p) => p,
  });
  const added = new Set(lines.map((l) => l.product_id));
  const matches = (searchQ.data?.items ?? []).filter((p) => !added.has(p.id)).slice(0, 8);

  const create = useMutation({
    mutationFn: () => salesApi.createOrder({
      customer_id: customerId, location_id: locationId,
      lines: lines.map((l) => ({ product_id: l.product_id, qty: Number(l.qty), unit_price: Number(l.unit_price) })),
    }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["sales"] }); onClose(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create order."),
  });

  const valid = customerId && locationId && lines.length > 0 && lines.every((l) => Number(l.qty) > 0);

  return (
    <Modal title="New sales order" size="xl" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>
          {create.isPending ? "Creating…" : "Create order"}
        </Button>
      </>
    }>
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Customer</span>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={`${INPUT} w-full`}>
              <option value="">— choose —</option>
              {(customers.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Selling location</span>
            <select value={locationId} onChange={(e) => setLocationId(e.target.value)} className={`${INPUT} w-full`}>
              <option value="">— choose —</option>
              {warehouses.list.map((w) => <option key={w.id} value={w.id}>{locLabel(w)}</option>)}
            </select></label>
        </div>
        <div>
          <span className="mb-1 block text-sm font-medium text-slate-700">Add products</span>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name or SKU" className={`${INPUT} w-full`} />
          {term.length >= 2 && matches.length > 0 && (
            <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-slate-200">
              {matches.map((p) => (
                <button key={p.id} onClick={() => { setLines((ls) => [...ls, { product_id: p.id, sku: p.sku, name: p.name, qty: "1", unit_price: String(Number(p.selling_price ?? 0)) }]); setSearch(""); }}
                  className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50">
                  <span><span className="font-medium">{p.name}</span> <span className="font-mono text-xs text-slate-400">{p.sku}</span></span>
                  <Plus className="h-3.5 w-3.5 text-brand-600" />
                </button>
              ))}
            </div>
          )}
        </div>
        {lines.length > 0 && (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 font-medium">Item</th><th className="py-2 text-right font-medium">Qty</th>
              <th className="py-2 text-right font-medium">Unit price</th><th /></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {lines.map((l, i) => (
                <tr key={l.product_id}>
                  <td className="py-2"><div className="font-medium text-slate-800">{l.name}</div>
                    <div className="font-mono text-xs text-slate-400">{l.sku}</div></td>
                  <td className="py-2 text-right"><input type="number" min={1} value={l.qty}
                    onChange={(e) => setLines((ls) => ls.map((x, j) => j === i ? { ...x, qty: e.target.value } : x))}
                    className={`${INPUT} w-16 text-right`} /></td>
                  <td className="py-2 text-right"><input type="number" min={0} value={l.unit_price}
                    onChange={(e) => setLines((ls) => ls.map((x, j) => j === i ? { ...x, unit_price: e.target.value } : x))}
                    className={`${INPUT} w-24 text-right`} /></td>
                  <td className="py-2 text-right"><button onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                    className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Modal>
  );
}

function OrderDetailModal({ orderId, onClose, onPay }: { orderId: string; onClose: () => void; onPay: (id: string) => void }) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const { data: o, isLoading } = useQuery({ queryKey: ["sales", "order", orderId], queryFn: () => salesApi.getOrder(orderId) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["sales"] }); };
  const onErr = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Action failed.");

  const confirm = useMutation({ mutationFn: () => salesApi.confirmOrder(orderId), onSuccess: refresh, onError: onErr });
  const deliver = useMutation({ mutationFn: () => salesApi.deliverOrder(orderId), onSuccess: refresh, onError: onErr });
  const invoice = useMutation({
    mutationFn: () => salesApi.createInvoice({ sales_order_id: orderId }),
    onSuccess: (inv) => { refresh(); onClose(); onPay(inv.id); }, onError: onErr,
  });

  const status = o?.status ?? "";
  const busy = confirm.isPending || deliver.isPending || invoice.isPending;
  const { hasPermission } = useAuth();

  return (
    <Modal title={o ? `Order ${o.so_number}` : "Sales order"} size="xl" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Close</Button>
        {o && status === "draft" && hasPermission("sales.order") && (
          <Button disabled={busy} onClick={() => { setErr(null); confirm.mutate(); }}>
            {confirm.isPending ? "Reserving…" : "Confirm & reserve"}</Button>)}
        {o && ["confirmed", "reserved", "picking", "partially_delivered"].includes(status) && hasPermission("sales.deliver") && (
          <Button disabled={busy} onClick={() => { setErr(null); deliver.mutate(); }}>
            {deliver.isPending ? "Delivering…" : "Deliver (issue stock)"}</Button>)}
        {o && ["partially_delivered", "delivered", "confirmed", "reserved"].includes(status) && hasPermission("sales.invoice") && (
          <Button disabled={busy} onClick={() => { setErr(null); invoice.mutate(); }}>
            {invoice.isPending ? "Invoicing…" : "Create invoice"}</Button>)}
      </>
    }>
      {isLoading || !o ? <div className="flex h-32 items-center justify-center"><Spinner label="Loading…" /></div> : (
        <div className="space-y-4">
          {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <F label="Status"><StatusBadge status={o.status} /></F>
            <F label="Customer">{o.customer_name ?? "—"}</F>
            <F label="Location">{o.location_name ?? "—"}</F>
            <F label="Total">{formatMoney(o.grand_total)}</F>
            {o.quote_number && <F label="From quote">{o.quote_number}</F>}
          </div>
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 font-medium">Item</th><th className="py-2 text-right font-medium">Qty</th>
              <th className="py-2 text-right font-medium">Reserved</th><th className="py-2 text-right font-medium">Delivered</th>
              <th className="py-2 text-right font-medium">Price</th><th className="py-2 text-right font-medium">Total</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {o.lines.map((l) => (
                <tr key={l.id}>
                  <td className="py-2"><div className="font-medium text-slate-800">{l.name ?? l.product_id}</div>
                    <div className="font-mono text-xs text-slate-400">{l.sku}</div></td>
                  <td className="py-2 text-right font-mono">{l.qty}</td>
                  <td className="py-2 text-right font-mono text-amber-700">{l.reserved_qty}</td>
                  <td className="py-2 text-right font-mono text-emerald-700">{l.delivered_qty}</td>
                  <td className="py-2 text-right font-mono">{formatMoney(l.unit_price)}</td>
                  <td className="py-2 text-right font-mono">{formatMoney(l.line_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

function VoidInvoiceModal({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const doVoid = useMutation({
    mutationFn: () => salesApi.voidInvoice(invoice.id, reason.trim()),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["sales"] }); onClose(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not void the sale."),
  });
  return (
    <Modal title={`Void ${invoice.invoice_number}`} size="md" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!reason.trim() || doVoid.isPending} onClick={() => { setErr(null); doVoid.mutate(); }}>
          {doVoid.isPending ? "Voiding…" : "Void sale"}
        </Button>
      </>
    }>
      <div className="space-y-3 text-sm">
        <div className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800">
          This reverses the sale: stock is restored, a sold bike returns to available, and the sale is
          excluded from active totals. The invoice is kept for the audit trail — it is not deleted.
        </div>
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{err}</div>}
        <label className="block">
          <span className="mb-1 block font-medium text-slate-700">Reason (required)</span>
          <textarea className={`${INPUT} w-full`} rows={3} value={reason} autoFocus
            onChange={(e) => setReason(e.target.value)} placeholder="Why is this sale being voided?" />
        </label>
      </div>
    </Modal>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CreditNoteRow({ cn, canReturn }: { cn: any; canReturn: boolean }) {
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: (action: "approve" | "apply" | "cancel") => salesApi.creditNoteAction(cn.id, action),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sales"] }),
  });
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-4 py-3 font-mono text-[13px] font-medium">{cn.credit_note_number}</td>
      <td className="px-4 py-3 text-slate-600">{cn.customer_name ?? "—"}</td>
      <td className="px-4 py-3 font-mono text-xs text-slate-500">{cn.invoice_number ?? "—"}</td>
      <td className="px-4 py-3"><StatusBadge status={cn.status} /></td>
      <td className="px-4 py-3 text-right font-mono">{formatMoney(cn.grand_total)}</td>
      <td className="px-4 py-3 text-right">
        {canReturn && cn.status === "draft" && (
          <Button variant="secondary" disabled={act.isPending} onClick={() => act.mutate("approve")}>Approve</Button>
        )}
        {canReturn && cn.status === "approved" && (
          <Button disabled={act.isPending} onClick={() => act.mutate("apply")}>Apply</Button>
        )}
      </td>
    </tr>
  );
}

function ReturnModal({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient();
  const warehouses = useWarehouses();
  const branches = useBranches();
  const locLabel = (w: { name: string; branch_id: string | null }) => {
    const b = w.branch_id ? branches.map.get(w.branch_id) : undefined;
    return b ? `${b.name} · ${w.name}` : w.name;
  };
  const [locationId, setLocationId] = useState("");
  const [reason, setReason] = useState("damaged");
  const [qty, setQty] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: async () => {
      const lines = invoice.lines
        .filter((l) => l.product_id && Number(qty[l.id] || 0) > 0)
        .map((l) => ({ product_id: l.product_id as string, qty: Number(qty[l.id] || 0) }));
      const ret = await salesApi.createReturn({ invoice_id: invoice.id, location_id: locationId, reason, lines });
      // Raise the matching credit note straight away.
      await salesApi.createCreditNote(ret.id);
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["sales"] }); onClose(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Return failed."),
  });

  const anyQty = invoice.lines.some((l) => Number(qty[l.id] || 0) > 0);

  return (
    <Modal title={`Return against ${invoice.invoice_number}`} size="lg" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!locationId || !anyQty || create.isPending}
          onClick={() => { setErr(null); create.mutate(); }}>
          {create.isPending ? "Processing…" : "Return & credit"}</Button>
      </>
    }>
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Return to location</span>
            <select value={locationId} onChange={(e) => setLocationId(e.target.value)} className={`${INPUT} w-full`}>
              <option value="">— choose —</option>
              {warehouses.list.map((w) => <option key={w.id} value={w.id}>{locLabel(w)}</option>)}
            </select></label>
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Reason</span>
            <select value={reason} onChange={(e) => setReason(e.target.value)} className={`${INPUT} w-full`}>
              {RETURN_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select></label>
        </div>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 font-medium">Item</th><th className="py-2 text-right font-medium">Sold</th>
            <th className="py-2 text-right font-medium">Return qty</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {invoice.lines.map((l) => (
              <tr key={l.id}>
                <td className="py-2"><div className="font-medium text-slate-800">{l.name ?? l.product_id}</div>
                  <div className="font-mono text-xs text-slate-400">{l.sku}</div></td>
                <td className="py-2 text-right font-mono text-slate-500">{l.qty}</td>
                <td className="py-2 text-right">
                  <input type="number" min={0} max={l.qty} value={qty[l.id] ?? ""}
                    onChange={(e) => setQty((m) => ({ ...m, [l.id]: e.target.value }))}
                    className={`${INPUT} w-20 text-right`} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}

function F({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex items-center gap-2"><span className="text-slate-400">{label}:</span>
    <span className="font-medium text-slate-700">{children}</span></div>;
}
