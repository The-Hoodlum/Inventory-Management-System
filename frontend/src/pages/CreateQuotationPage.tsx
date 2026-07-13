// Create Quotation — build a quotation for a customer from spare-part lines, see the
// VAT-aware totals live (parts are VAT-exclusive; VAT is added at the tenant rate and the
// ZMW payable uses the current fx rate), then save, print the branded PDF, and convert it
// straight to a sales order without re-entering anything. Customer is selectable from the
// list or entered inline (which creates the customer record).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { customersApi, useCustomers } from "@/lib/customers";
import { formatMoney } from "@/lib/format";
import { motorcyclesApi } from "@/lib/motorcycles";
import { useWarehouses } from "@/lib/refdata";
import { type Quotation, type QuotationConvertResult, type QuotationInvoiceResult, salesApi } from "@/lib/sales";
import { tenantApi } from "@/lib/tenantSettings";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

interface Line {
  product_id: string;
  sku: string;
  name: string;
  qty: number;
  unit_price: number;   // USD
}

interface BikeLine {
  unit_id: string;
  chassis: string;
  label: string;
  price: number;        // ZMW, VAT-inclusive
}

export default function CreateQuotationPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const customers = useCustomers();
  const warehouses = useWarehouses();
  const settings = useQuery({ queryKey: ["tenant", "settings"], queryFn: tenantApi.get });
  const vatRate = Number(settings.data?.vat_rate ?? 0);
  const fx = Number(settings.data?.fx_rate ?? 1);

  const [customerId, setCustomerId] = useState("");
  const [inlineNew, setInlineNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newAddr, setNewAddr] = useState("");
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [bikeSearch, setBikeSearch] = useState("");
  const [bikeLines, setBikeLines] = useState<BikeLine[]>([]);
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<Quotation | null>(null);
  const [convertLoc, setConvertLoc] = useState("");
  const [convertMsg, setConvertMsg] = useState<string | null>(null);
  const [invoiceResult, setInvoiceResult] = useState<QuotationInvoiceResult | null>(null);

  const term = search.trim();
  const searchQ = useQuery({
    queryKey: ["quote-part-search", term],
    queryFn: () => catalogApi.products({ search: term, page: 1, page_size: 8 }),
    enabled: term.length >= 2,
    placeholderData: (p) => p,
  });
  const inLines = new Set(lines.map((l) => l.product_id));
  const matches = (searchQ.data?.items ?? []).filter((p) => !inLines.has(p.id)).slice(0, 8);

  // Bikes available to quote (assembled/reserved), searched by chassis/engine/model.
  const bterm = bikeSearch.trim();
  const bikeQ = useQuery({
    queryKey: ["quote-bike-search", bterm],
    queryFn: () => motorcyclesApi.listUnits({ search: bterm, sold: false, page_size: 12 }),
    enabled: bterm.length >= 2,
    placeholderData: (p) => p,
  });
  const inBikes = new Set(bikeLines.map((b) => b.unit_id));
  const bikeMatches = (bikeQ.data?.items ?? [])
    .filter((u) => u.allowed_next.includes("sold") && !inBikes.has(u.id)).slice(0, 8);

  // Everything is shown in ZMW: parts (USD) are converted at fx; bikes are already ZMW
  // (VAT-inclusive). Parts add VAT on top; bikes have VAT extracted from the price.
  const partsNetZmw = useMemo(() => lines.reduce((s, l) => s + l.qty * l.unit_price, 0) * fx, [lines, fx]);
  const partsVatZmw = partsNetZmw * vatRate;
  const bikesGrossZmw = useMemo(() => bikeLines.reduce((s, b) => s + b.price, 0), [bikeLines]);
  const bikesNetZmw = vatRate > 0 ? bikesGrossZmw / (1 + vatRate) : bikesGrossZmw;
  const bikesVatZmw = bikesGrossZmw - bikesNetZmw;
  const netZmw = partsNetZmw + bikesNetZmw;
  const vatZmw = partsVatZmw + bikesVatZmw;
  const totalZmw = partsNetZmw + partsVatZmw + bikesGrossZmw;

  function add(p: { id: string; sku: string; name: string; selling_price?: number | string }) {
    setLines((c) => [...c, { product_id: p.id, sku: p.sku, name: p.name, qty: 1, unit_price: Number(p.selling_price ?? 0) }]);
    setSearch("");
  }
  const setLine = (i: number, patch: Partial<Line>) =>
    setLines((c) => c.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  function addBike(u: { id: string; chassis_number: string; model_name: string | null; colour_name: string | null; selling_price: number | null }) {
    const label = [u.model_name ?? "Bike", u.colour_name].filter(Boolean).join(" · ");
    setBikeLines((c) => [...c, { unit_id: u.id, chassis: u.chassis_number, label, price: Number(u.selling_price ?? 0) }]);
    setBikeSearch("");
  }
  const setBike = (i: number, patch: Partial<BikeLine>) =>
    setBikeLines((c) => c.map((b, j) => (j === i ? { ...b, ...patch } : b)));

  const save = useMutation({
    mutationFn: async () => {
      let cid = customerId;
      if (inlineNew) {
        const created = await customersApi.create({
          name: newName.trim(),
          phone: newPhone.trim() || null,
          addresses: newAddr.trim() ? [{ line1: newAddr.trim(), address_type: "billing", is_default: true }] : undefined,
        });
        cid = created.id;
      }
      return salesApi.createQuotation({
        customer_id: cid,
        notes: notes.trim() || null,
        lines: lines.map((l) => ({ product_id: l.product_id, qty: l.qty, unit_price: l.unit_price })),
        bike_lines: bikeLines.map((b) => ({ unit_id: b.unit_id, price: b.price })),
      });
    },
    onSuccess: (q) => {
      setSaved(q);
      void qc.invalidateQueries({ queryKey: ["sales", "quotes"] });
      void customers.refetch?.();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the quotation."),
  });

  const convert = useMutation({
    mutationFn: () => salesApi.convertQuotation(
      saved!.id, saved!.lines.some((l) => !l.is_bike) ? convertLoc : null),
    onSuccess: (res: QuotationConvertResult) => {
      void qc.invalidateQueries({ queryKey: ["sales"] });
      const parts = res.sales_order ? `order ${res.sales_order.so_number}` : "";
      const bikes = res.bike_sales.length ? `${res.bike_sales.length} bike sale(s)` : "";
      setErr(null);
      setConvertMsg([parts, bikes].filter(Boolean).join(" + ") || "converted");
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not convert."),
  });

  const toInvoice = useMutation({
    mutationFn: () => salesApi.invoiceQuotation(
      saved!.id, saved!.lines.some((l) => !l.is_bike) ? convertLoc : null),
    onSuccess: (res: QuotationInvoiceResult) => {
      void qc.invalidateQueries({ queryKey: ["sales"] });
      setErr(null);
      setInvoiceResult(res);
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the invoice."),
  });
  // Every invoice this conversion produced (the parts invoice + one per bike), for printing.
  const invoiceDocs = invoiceResult
    ? [...(invoiceResult.invoice ? [invoiceResult.invoice] : []), ...invoiceResult.bike_sales.map((b) => b.invoice)]
    : [];
  const needsLoc = !!saved && saved.lines.some((l) => !l.is_bike);
  const convertBusy = convert.isPending || toInvoice.isPending;

  const customerValid = inlineNew ? newName.trim().length > 0 : customerId.length > 0;
  const canSave = customerValid && (lines.length > 0 || bikeLines.length > 0)
    && lines.every((l) => l.qty > 0) && bikeLines.every((b) => b.price > 0);

  if (saved) {
    return (
      <div>
        <PageHeader title="Quotation saved" description={`Quotation ${saved.quote_number} is ready.`} />
        <Card className="mx-auto max-w-lg space-y-4 p-6">
          <div className="flex items-center gap-2 text-emerald-700">
            <Check className="h-5 w-5" /><span className="font-semibold">Saved {saved.quote_number}</span>
          </div>
          <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm">
            <Row label="Customer" value={saved.customer_name ?? "—"} />
            <Row label="Net (ZMW)" value={formatMoney(saved.net_total, "ZMW")} />
            <Row label={`VAT${saved.vat_rate ? ` (${(saved.vat_rate * 100).toFixed(0)}%)` : ""}`} value={formatMoney(saved.tax_total, "ZMW")} />
            <Row label="Total (ZMW)" value={formatMoney(saved.grand_total_zmw || saved.grand_total, "ZMW")} bold />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => void salesApi.downloadQuotationPdf(saved.id, saved.quote_number)}>
              Print PDF
            </Button>
            <Button variant="secondary" onClick={() => { setSaved(null); setLines([]); setBikeLines([]); setNotes(""); setConvertMsg(null); setInvoiceResult(null); }}>
              New quotation
            </Button>
            <Button variant="secondary" onClick={() => navigate("/sales")}>Go to Sales</Button>
          </div>
          <div className="border-t border-slate-200 pt-4">
            <div className="mb-1 text-sm font-medium text-slate-700">Convert without re-entry</div>
            <p className="mb-2 text-xs text-slate-500">
              Turn this quotation into an invoice (parts are invoiced via a stock-reserving order;
              each bike becomes its own invoice), or into a sales order to fulfil later.
            </p>
            {err && <div className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
            {invoiceResult ? (
              <div className="space-y-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                <div className="font-medium">Invoice(s) created — print and give to the customer:</div>
                {invoiceDocs.map((inv) => (
                  <div key={inv.id} className="flex items-center justify-between gap-2">
                    <span className="font-mono">
                      {inv.invoice_number} · {formatMoney(inv.grand_total_zmw || inv.grand_total, "ZMW")}
                    </span>
                    <Button variant="secondary" onClick={() => void salesApi.downloadInvoicePdf(inv.id, inv.invoice_number)}>
                      Print
                    </Button>
                  </div>
                ))}
                <button className="underline" onClick={() => navigate("/sales")}>View in Sales →</button>
              </div>
            ) : convertMsg ? (
              <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                Converted: {convertMsg}. <button className="underline" onClick={() => navigate("/sales")}>View in Sales →</button>
              </div>
            ) : (
              <div className="space-y-2">
                {needsLoc && (
                  <select className={`${INPUT} w-full`} value={convertLoc} onChange={(e) => setConvertLoc(e.target.value)}>
                    <option value="">Select location (for parts)…</option>
                    {warehouses.list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </select>
                )}
                <div className="flex items-center gap-2">
                  <Button className="flex-1 justify-center" disabled={convertBusy || (needsLoc && !convertLoc)}
                    onClick={() => { setErr(null); toInvoice.mutate(); }}>
                    {toInvoice.isPending ? "Invoicing…" : "Convert to invoice"}
                  </Button>
                  <Button variant="secondary" disabled={convertBusy || (needsLoc && !convertLoc)}
                    onClick={() => { setErr(null); convert.mutate(); }}>
                    {convert.isPending ? "Converting…" : "To sales order"}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Create Quotation"
        description="Quote bikes (by chassis) and spare parts together. Everything is totalled in ZMW; parts add VAT, bikes are VAT-inclusive. Save, print, and convert without re-entering."
      />
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* Customer + lines */}
        <Card className="space-y-4 p-4">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">Customer *</span>
              <button className="text-xs text-brand-600 hover:underline" onClick={() => setInlineNew((v) => !v)}>
                {inlineNew ? "Pick existing" : "+ New customer"}
              </button>
            </div>
            {inlineNew ? (
              <div className="grid grid-cols-2 gap-2">
                <input className={INPUT} placeholder="Name *" value={newName} onChange={(e) => setNewName(e.target.value)} />
                <input className={INPUT} placeholder="Phone" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} />
                <input className={`${INPUT} col-span-2`} placeholder="Address" value={newAddr} onChange={(e) => setNewAddr(e.target.value)} />
              </div>
            ) : (
              <select className={`${INPUT} w-full`} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="">Select customer…</option>
                {(customers.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
          </div>

          <div>
            <div className="mb-1 text-sm font-medium text-slate-700">Add parts</div>
            <input className={`${INPUT} w-full`} placeholder="Search part (name / SKU)" value={search}
              onChange={(e) => setSearch(e.target.value)} />
            {term.length >= 2 && (
              <div className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-200">
                {searchQ.isFetching && matches.length === 0 ? (
                  <div className="p-3"><Spinner label="Searching…" /></div>
                ) : matches.length === 0 ? (
                  <div className="p-3 text-sm text-slate-400">No matching parts.</div>
                ) : (
                  matches.map((p) => (
                    <button key={p.id} onClick={() => add(p)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50">
                      <span><span className="font-medium text-slate-800">{p.name}</span>
                        <span className="ml-2 font-mono text-xs text-slate-400">{p.sku}</span></span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        {formatMoney(Number(p.selling_price ?? 0))}<Plus className="h-3.5 w-3.5 text-brand-600" /></span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>

          {lines.length > 0 && (
            <div className="space-y-2">
              {lines.map((l, i) => (
                <div key={l.product_id} className="flex items-center gap-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-800">{l.name}</div>
                    <div className="font-mono text-xs text-slate-400">{l.sku}</div>
                  </div>
                  <input type="number" min={1} value={l.qty} className={`${INPUT} w-14 text-right`}
                    onChange={(e) => setLine(i, { qty: Math.max(1, Number(e.target.value)) })} />
                  <input type="number" min={0} value={l.unit_price} className={`${INPUT} w-20 text-right`}
                    onChange={(e) => setLine(i, { unit_price: Number(e.target.value) })} />
                  <div className="w-20 text-right font-mono text-slate-700">{formatMoney(l.qty * l.unit_price)}</div>
                  <button onClick={() => setLines((c) => c.filter((_, j) => j !== i))}
                    className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          )}

          <div>
            <div className="mb-1 text-sm font-medium text-slate-700">Add bikes</div>
            <input className={`${INPUT} w-full`} placeholder="Search bike (chassis / engine / model)" value={bikeSearch}
              onChange={(e) => setBikeSearch(e.target.value)} />
            {bterm.length >= 2 && (
              <div className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-200">
                {bikeQ.isFetching && bikeMatches.length === 0 ? (
                  <div className="p-3"><Spinner label="Searching…" /></div>
                ) : bikeMatches.length === 0 ? (
                  <div className="p-3 text-sm text-slate-400">No available bike matches (assembled/reserved only).</div>
                ) : (
                  bikeMatches.map((u) => (
                    <button key={u.id} onClick={() => addBike(u)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50">
                      <span><span className="font-mono text-[13px] text-slate-800">{u.chassis_number}</span>
                        <span className="ml-2 text-xs text-slate-400">{[u.model_name, u.colour_name].filter(Boolean).join(" · ")}</span></span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        {formatMoney(Number(u.selling_price ?? 0), "ZMW")}<Plus className="h-3.5 w-3.5 text-brand-600" /></span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>

          {bikeLines.length > 0 && (
            <div className="space-y-2">
              {bikeLines.map((b, i) => (
                <div key={b.unit_id} className="flex items-center gap-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[13px] text-slate-800">{b.chassis}</div>
                    <div className="text-xs text-slate-400">{b.label} · VAT-inclusive</div>
                  </div>
                  <input type="number" min={0} value={b.price} className={`${INPUT} w-24 text-right`}
                    onChange={(e) => setBike(i, { price: Number(e.target.value) })} />
                  <div className="w-16 text-right text-2xs text-slate-400">ZMW</div>
                  <button onClick={() => setBikeLines((c) => c.filter((_, j) => j !== i))}
                    className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          )}

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Notes</span>
            <textarea className={`${INPUT} w-full`} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </Card>

        {/* Totals + save */}
        <Card className="flex flex-col p-4">
          <div className="mb-2 text-sm font-semibold text-slate-800">Quotation total (ZMW)</div>
          <div className="flex-1 space-y-2 text-sm">
            <Row label="Net" value={formatMoney(netZmw, "ZMW")} />
            <Row label={`VAT (${(vatRate * 100).toFixed(0)}%)`} value={formatMoney(vatZmw, "ZMW")} />
            <div className="border-t border-slate-200 pt-2">
              <Row label="Total" value={formatMoney(totalZmw, "ZMW")} bold />
            </div>
            <p className="pt-2 text-xs text-slate-400">
              Parts are VAT-exclusive (VAT added on top, converted at rate {fx}); bikes are VAT-inclusive (VAT extracted, priced in ZMW).
            </p>
          </div>
          {err && <div className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
          <Button className="mt-3 w-full justify-center" disabled={!canSave || save.isPending}
            onClick={() => { setErr(null); save.mutate(); }}>
            {save.isPending ? "Saving…" : "Save quotation"}
          </Button>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className={`flex items-center justify-between ${bold ? "text-base font-semibold text-slate-900" : "text-slate-600"}`}>
      <span>{label}</span><span className="font-mono">{value}</span>
    </div>
  );
}
