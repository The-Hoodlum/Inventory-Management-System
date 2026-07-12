// Sell a serialized motorcycle from POS or Sales: pick a bike by chassis, confirm the
// price + customer, optionally take payment, and complete. Creates a branded invoice,
// marks the unit sold, and (with payment) issues a receipt — one call to /sales/bike-sale.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useCustomers } from "@/lib/customers";
import { formatMoney } from "@/lib/format";
import { motorcyclesApi } from "@/lib/motorcycles";
import { type BikeSaleResult, salesApi } from "@/lib/sales";

const INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const METHODS = ["cash", "card", "mobile_money", "bank_transfer", "cheque"] as const;

interface PickedBike { id: string; chassis: string; engine: string | null; model: string | null; price: number }

export function SellBikeModal({ onClose, onSold }: { onClose: () => void; onSold?: (r: BikeSaleResult) => void }) {
  const customers = useCustomers();
  const [search, setSearch] = useState("");
  const [bike, setBike] = useState<PickedBike | null>(null);
  const [price, setPrice] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [takePayment, setTakePayment] = useState(true);
  const [method, setMethod] = useState<(typeof METHODS)[number]>("cash");
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<BikeSaleResult | null>(null);

  const bikeQ = useQuery({
    queryKey: ["sell-bike-search", search],
    queryFn: () => motorcyclesApi.listUnits({ search: search.trim(), sold: false, page_size: 8 }),
    enabled: search.trim().length >= 2 && !bike,
  });
  // Only units the lifecycle allows selling (assembled / reserved).
  const sellable = (bikeQ.data?.items ?? []).filter((u) => u.allowed_next.includes("sold"));

  const priceNum = Number(price) || 0;
  const amountNum = Number(amount) || 0;

  const sell = useMutation({
    mutationFn: () => salesApi.sellBike({
      unit_id: bike!.id,
      customer_id: customerId || null,
      price: priceNum,
      payments: takePayment && amountNum > 0 ? [{ method, amount: amountNum }] : [],
    }),
    onSuccess: (r) => { setDone(r); onSold?.(r); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not complete the sale."),
  });

  function pick(u: { id: string; chassis_number: string; engine_number: string | null; model_name: string | null; selling_price: number | null }) {
    const p = Number(u.selling_price ?? 0);
    setBike({ id: u.id, chassis: u.chassis_number, engine: u.engine_number, model: u.model_name, price: p });
    setPrice(p ? String(p) : "");
    setAmount(p ? String(p) : "");
    setSearch("");
  }

  if (done) {
    return (
      <Modal title="Bike sold" size="md" onClose={onClose} footer={
        <>
          <Button variant="secondary" onClick={() => void salesApi.downloadInvoicePdf(done.invoice.id, done.invoice.invoice_number)}>Print invoice</Button>
          <Button onClick={onClose}>Done</Button>
        </>
      }>
        <div className="space-y-2 text-sm">
          <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">
            <b>{done.chassis_number}</b>{done.model_name ? ` · ${done.model_name}` : ""} marked <b>sold</b>.
          </div>
          <div className="flex justify-between"><span className="text-slate-500">Invoice</span><span className="font-mono">{done.invoice.invoice_number}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Amount</span><span className="font-mono">{formatMoney(Number(done.invoice.grand_total_zmw ?? done.invoice.grand_total), "ZMW")}</span></div>
          {done.receipt && <div className="flex justify-between"><span className="text-slate-500">Receipt</span><span className="font-mono">{done.receipt.receipt_number}</span></div>}
          {!done.receipt && <div className="text-xs text-amber-600">Invoice only — record the payment later from Sales.</div>}
        </div>
      </Modal>
    );
  }

  const valid = bike && priceNum > 0 && (!takePayment || amountNum > 0);

  return (
    <Modal title="Sell a bike" size="lg" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid || sell.isPending} onClick={() => { setErr(null); sell.mutate(); }}>
          {sell.isPending ? "Selling…" : takePayment ? "Complete sale" : "Create invoice"}
        </Button>
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
              <button className="ml-auto text-xs text-slate-400 hover:text-red-600" onClick={() => setBike(null)}>change</button>
            </div>
          ) : (
            <>
              <input className={INPUT} placeholder="Search sellable bikes by chassis / engine" value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
              {search.trim().length >= 2 && (
                <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-slate-200">
                  {sellable.map((u) => (
                    <button key={u.id} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => pick(u)}>
                      <span className="font-mono text-[13px]">{u.chassis_number}</span>
                      <span className="text-xs text-slate-500">{u.model_name} · {formatMoney(Number(u.selling_price ?? 0), "ZMW")}</span>
                    </button>
                  ))}
                  {sellable.length === 0 && !bikeQ.isFetching && <div className="px-3 py-2 text-xs text-slate-400">No sellable bike matches.</div>}
                </div>
              )}
            </>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Price *">
            <input type="number" min={0} className={INPUT} value={price} onChange={(e) => { setPrice(e.target.value); if (takePayment) setAmount(e.target.value); }} />
          </Field>
          <Field label="Customer">
            <select className={INPUT} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              <option value="">Walk-in customer</option>
              {(customers.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={takePayment} onChange={(e) => setTakePayment(e.target.checked)} />
          Take payment now
        </label>
        {takePayment && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Method">
              <select className={INPUT} value={method} onChange={(e) => setMethod(e.target.value as (typeof METHODS)[number])}>
                {METHODS.map((m) => <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}
              </select>
            </Field>
            <Field label="Amount received">
              <input type="number" min={0} className={INPUT} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
          </div>
        )}
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">{label}</span>{children}</label>;
}
