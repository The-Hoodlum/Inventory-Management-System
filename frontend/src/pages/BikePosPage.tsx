// Bike POS — a purpose-built point of sale for SERIALIZED motorcycles. Browse the units
// available to sell (assembled / reserved), pick one by chassis, confirm price + customer,
// optionally take payment, and complete via the existing bike-sale flow (POST
// /sales/bike-sale): a branded invoice, the unit marked sold + linked, and a receipt. It
// does NOT sell fungible parts — those have their own Spare Parts POS. Bike prices are
// VAT-inclusive (VAT is extracted server-side; the customer pays the shown price).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bike, Check, Wrench } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useCustomers } from "@/lib/customers";
import { formatDate, formatMoney } from "@/lib/format";
import { type MotoUnit, motorcyclesApi, useMotoModels } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";
import { type BikeSaleResult, PAYMENT_METHODS, type PaymentMethod, salesApi } from "@/lib/sales";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function bikeLabel(u: { model_name: string | null; colour_name: string | null }) {
  return [u.model_name ?? "—", u.colour_name].filter(Boolean).join(" · ");
}

export default function BikePosPage() {
  const { hasPermission } = useAuth();
  const canSell = hasPermission("motorcycle.manage");
  const canSeeLog = hasPermission("sales.read");
  const branches = useBranches();
  const models = useMotoModels();
  const customers = useCustomers();
  const qc = useQueryClient();

  const [search, setSearch] = useState("");
  const [branchId, setBranchId] = useState("");
  const [modelId, setModelId] = useState("");
  const [bike, setBike] = useState<MotoUnit | null>(null);
  const [price, setPrice] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [takePayment, setTakePayment] = useState(true);
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<BikeSaleResult | null>(null);

  // Available-to-sell units. Only assembled + reserved units can be sold, so fetch those
  // statuses server-side (a plain sold=false page would be swamped by unassembled stock).
  const common = {
    search: search.trim() || undefined,
    branch_id: branchId || undefined,
    model_id: modelId || undefined,
    page_size: 100,
  };
  const assembledQ = useQuery({
    queryKey: ["bike-pos-units", "assembled", search, branchId, modelId],
    queryFn: () => motorcyclesApi.listUnits({ ...common, status: "assembled" }),
    placeholderData: (p) => p,
  });
  const reservedQ = useQuery({
    queryKey: ["bike-pos-units", "reserved", search, branchId, modelId],
    queryFn: () => motorcyclesApi.listUnits({ ...common, status: "reserved" }),
    placeholderData: (p) => p,
  });
  const unitsLoading = !assembledQ.data || !reservedQ.data;
  const unitsFetching = assembledQ.isFetching || reservedQ.isFetching;
  const sellable = [
    ...(assembledQ.data?.items ?? []),
    ...(reservedQ.data?.items ?? []),
  ].filter((u) => u.allowed_next.includes("sold"));

  const priceNum = Number(price) || 0;
  const amountNum = Number(amount) || 0;

  function pick(u: MotoUnit) {
    setBike(u);
    const p = Number(u.selling_price ?? 0);
    setPrice(p ? String(p) : "");
    setAmount(p ? String(p) : "");
    setErr(null);
  }

  const sell = useMutation({
    mutationFn: () =>
      salesApi.sellBike({
        unit_id: bike!.id,
        customer_id: customerId || null,
        price: priceNum,
        payments: takePayment && amountNum > 0 ? [{ method, amount: amountNum }] : [],
      }),
    onSuccess: (r) => {
      setDone(r);
      setBike(null);
      setPrice("");
      setAmount("");
      setCustomerId("");
      void qc.invalidateQueries({ queryKey: ["bike-pos-units"] });
      void qc.invalidateQueries({ queryKey: ["bike-sales-log"] });
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not complete the sale."),
  });

  const logQ = useQuery({
    queryKey: ["bike-sales-log", branchId],
    queryFn: () => salesApi.listMotorcycleSales({ branch_id: branchId || undefined, limit: 100 }),
    enabled: canSeeLog,
  });

  const valid = bike && priceNum > 0 && (!takePayment || amountNum > 0);

  return (
    <div>
      <PageHeader
        title="Bike POS"
        description="Sell a specific motorcycle by chassis. Prices are VAT-inclusive; completing the sale marks the unit sold, issues a branded invoice and (with payment) a receipt."
      />

      {!canSell ? (
        <Card className="p-8 text-center text-sm text-slate-500">
          You don't have permission to sell motorcycles.
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          {/* Available bikes */}
          <Card className="p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by chassis / engine / model"
                className={`${INPUT} min-w-0 flex-1`}
                autoFocus
              />
              <select className={INPUT} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
                <option value="">All branches</option>
                {branches.list.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
              <select className={INPUT} value={modelId} onChange={(e) => setModelId(e.target.value)}>
                <option value="">All models</option>
                {(models.data?.items ?? []).map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
              {unitsFetching && <Spinner />}
            </div>

            {unitsLoading ? (
              <div className="flex h-40 items-center justify-center"><Spinner label="Loading bikes…" /></div>
            ) : sellable.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-400">
                <Bike className="mx-auto mb-2 h-6 w-6 text-slate-300" />
                No available bikes match. Only assembled or reserved units can be sold.
              </div>
            ) : (
              <div className="max-h-[28rem] space-y-1.5 overflow-y-auto">
                {sellable.map((u) => {
                  const selected = bike?.id === u.id;
                  return (
                    <button
                      key={u.id}
                      onClick={() => pick(u)}
                      className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm transition ${
                        selected
                          ? "border-brand-500 bg-brand-50"
                          : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block font-mono text-[13px] text-slate-800">{u.chassis_number}</span>
                        <span className="block truncate text-xs text-slate-500">
                          {bikeLabel(u)} · eng {u.engine_number ?? "—"}
                          {u.status === "reserved" ? " · reserved" : ""}
                        </span>
                      </span>
                      <span className="ml-2 shrink-0 font-mono text-xs text-slate-600">
                        {formatMoney(Number(u.selling_price ?? 0))}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Sell panel */}
          <Card className="flex flex-col p-4">
            <div className="mb-2 text-sm font-semibold text-slate-800">Sell</div>
            {!bike ? (
              <div className="flex-1 rounded-lg bg-slate-50 px-3 py-8 text-center text-sm text-slate-400">
                Pick a bike on the left to start a sale.
              </div>
            ) : (
              <div className="flex-1 space-y-3">
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                  <div className="font-mono text-[13px] text-slate-800">{bike.chassis_number}</div>
                  <div className="text-xs text-slate-500">{bikeLabel(bike)} · engine {bike.engine_number ?? "—"}</div>
                </div>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">Price (VAT-inclusive) *</span>
                  <input type="number" min={0} className={`${INPUT} w-full`} value={price}
                    onChange={(e) => { setPrice(e.target.value); if (takePayment) setAmount(e.target.value); }} />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">Customer</span>
                  <select className={`${INPUT} w-full`} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                    <option value="">Walk-in customer</option>
                    {(customers.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={takePayment} onChange={(e) => setTakePayment(e.target.checked)} />
                  Take payment now
                </label>
                {takePayment && (
                  <div className="grid grid-cols-2 gap-2">
                    <select className={INPUT} value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
                      {PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                    <input type="number" min={0} className={`${INPUT} text-right`} value={amount}
                      placeholder="Amount received" onChange={(e) => setAmount(e.target.value)} />
                  </div>
                )}
                {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
              </div>
            )}
            <Button
              className="mt-3 w-full justify-center"
              disabled={!valid || sell.isPending}
              onClick={() => { setErr(null); sell.mutate(); }}
            >
              {sell.isPending ? "Selling…" : takePayment ? `Charge ${formatMoney(priceNum)}` : "Create invoice"}
            </Button>
          </Card>
        </div>
      )}

      {/* Completed sale */}
      {done && (
        <Card className="mx-auto mt-4 max-w-md p-5 text-sm">
          <div className="mb-2 flex items-center gap-2 text-emerald-700">
            <Check className="h-5 w-5" /><span className="font-semibold">Bike sold</span>
          </div>
          <div className="mb-2 rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">
            <b>{done.chassis_number}</b>{done.model_name ? ` · ${done.model_name}` : ""} marked sold.
          </div>
          <div className="flex justify-between"><span className="text-slate-500">Invoice</span>
            <span className="font-mono">{done.invoice.invoice_number}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Amount</span>
            <span className="font-mono">{formatMoney(Number(done.invoice.grand_total_zmw ?? done.invoice.grand_total))}</span></div>
          {done.receipt ? (
            <div className="flex justify-between"><span className="text-slate-500">Receipt</span>
              <span className="font-mono">{done.receipt.receipt_number}</span></div>
          ) : (
            <div className="text-xs text-amber-600">Invoice only — record the payment later from Sales.</div>
          )}
          <div className="mt-3 flex gap-2">
            <Button variant="secondary" className="flex-1 justify-center"
              onClick={() => void salesApi.downloadInvoicePdf(done.invoice.id, done.invoice.invoice_number)}>
              Print invoice
            </Button>
            <Button className="flex-1 justify-center" onClick={() => setDone(null)}>New sale</Button>
          </div>
        </Card>
      )}

      {/* Recent bike sales */}
      {canSeeLog && (
        <Card className="mt-6 overflow-hidden">
          <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-800">
            <Wrench className="h-4 w-4 text-brand-600" /> Recent bike sales
          </div>
          {logQ.isLoading ? (
            <div className="flex h-32 items-center justify-center"><Spinner label="Loading sales…" /></div>
          ) : (logQ.data ?? []).length === 0 ? (
            <div className="p-10 text-center text-sm text-slate-400">No bike sales yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2.5 font-medium">Date</th>
                    <th className="px-4 py-2.5 font-medium">Chassis</th>
                    <th className="px-4 py-2.5 font-medium">Bike</th>
                    <th className="px-4 py-2.5 text-right font-medium">Amount</th>
                    <th className="px-4 py-2.5 font-medium">Customer</th>
                    <th className="px-4 py-2.5 font-medium">Invoice</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(logQ.data ?? []).map((s) => (
                    <tr key={`${s.unit_id}-${s.invoice_id ?? "hist"}`} className="hover:bg-slate-50">
                      <td className="px-4 py-3 text-slate-600">{formatDate(s.sale_date)}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-700">{s.chassis_number}</td>
                      <td className="px-4 py-3 text-slate-700">{bikeLabel(s)}</td>
                      <td className="px-4 py-3 text-right font-mono font-medium text-slate-800">{formatMoney(s.revenue)}</td>
                      <td className="px-4 py-3 text-slate-600">{s.customer_name ?? "—"}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">
                        {s.invoice_number ?? (s.historical ? "hist." : "—")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
