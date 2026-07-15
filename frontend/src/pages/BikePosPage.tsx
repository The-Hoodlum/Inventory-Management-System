// Bike POS — a purpose-built point of sale for SERIALIZED motorcycles. Build a cart of one
// or more bikes (assembled or unassembled) for ONE customer, confirm each price, optionally
// take payment, and complete via POST /sales/bike-sale/bulk: a single branded invoice with
// a line per bike, every unit marked sold + linked, and one receipt. Selling several bikes
// to one customer is one transaction (all-or-nothing). It does NOT sell fungible parts —
// those have their own Spare Parts POS. Bike prices are VAT-inclusive (extracted server-side).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bike, Check, Plus, Wrench, X } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { AssemblyBadge } from "@/components/AssemblyBadge";
import { PageHeader } from "@/components/PageHeader";
import { emptyPaymentRow, type PaymentRow, PaymentRows, paymentRowsTotal, toPaymentLines } from "@/components/PaymentRows";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useCustomers } from "@/lib/customers";
import { formatDate, formatMoney } from "@/lib/format";
import { assemblyState, type MotoUnit, motorcyclesApi, useMotoModels } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";
import { type BulkBikeSaleResult, salesApi } from "@/lib/sales";

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
  const [cart, setCart] = useState<MotoUnit[]>([]);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [customerId, setCustomerId] = useState("");
  const [takePayment, setTakePayment] = useState(true);
  const [payRows, setPayRows] = useState<PaymentRow[]>([emptyPaymentRow("cash")]);
  // Selling bikes before they're assembled: assemblyRequired = the dealership assembles them
  // (queued + can't dispatch until done); unchecked = a reseller sale, delivered as-is.
  const [assemblyRequired, setAssemblyRequired] = useState(true);
  const [ackBeforeAssembly, setAckBeforeAssembly] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<BulkBikeSaleResult | null>(null);

  // Available-to-sell units: assembled, reserved AND unassembled (bikes can be sold before
  // assembly). Fetch each status server-side and show the ready ones first.
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
  const unassembledQ = useQuery({
    queryKey: ["bike-pos-units", "unassembled", search, branchId, modelId],
    queryFn: () => motorcyclesApi.listUnits({ ...common, status: "unassembled" }),
    placeholderData: (p) => p,
  });
  const unitsLoading = !assembledQ.data || !reservedQ.data || !unassembledQ.data;
  const unitsFetching = assembledQ.isFetching || reservedQ.isFetching || unassembledQ.isFetching;
  const sellable = [
    ...(assembledQ.data?.items ?? []),
    ...(reservedQ.data?.items ?? []),
    ...(unassembledQ.data?.items ?? []),
  ].filter((u) => u.allowed_next.includes("sold"));

  const inCart = new Set(cart.map((u) => u.id));
  const total = cart.reduce((sum, u) => sum + (Number(prices[u.id]) || 0), 0);
  const paidNum = paymentRowsTotal(payRows);
  const beforeAssembly = cart.some((u) => assemblyState(u) !== "assembled");
  const allPriced = cart.every((u) => (Number(prices[u.id]) || 0) > 0);
  const overpay = takePayment && paidNum > total + 0.001;
  const valid =
    cart.length > 0 && allPriced && (!takePayment || paidNum > 0) && !overpay &&
    (!beforeAssembly || ackBeforeAssembly);

  function toggle(u: MotoUnit) {
    setErr(null);
    if (inCart.has(u.id)) {
      setCart((c) => c.filter((x) => x.id !== u.id));
      return;
    }
    setCart((c) => [...c, u]);
    setPrices((p) => ({ ...p, [u.id]: p[u.id] ?? (u.selling_price ? String(u.selling_price) : "") }));
    setAckBeforeAssembly(false);
  }
  function remove(id: string) {
    setCart((c) => c.filter((x) => x.id !== id));
  }
  function clearSale() {
    setCart([]);
    setPrices({});
    setCustomerId("");
    setPayRows([emptyPaymentRow("cash")]);
    setAssemblyRequired(true);
    setAckBeforeAssembly(false);
  }

  const sell = useMutation({
    mutationFn: () =>
      salesApi.sellBikesBulk({
        customer_id: customerId || null,
        lines: cart.map((u) => ({
          unit_id: u.id,
          price: Number(prices[u.id]) || 0,
          assembly_required: assemblyState(u) !== "assembled" ? assemblyRequired : true,
        })),
        payments: takePayment ? toPaymentLines(payRows) : [],
      }),
    onSuccess: (r) => {
      setDone(r);
      clearSale();
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

  return (
    <div>
      <PageHeader
        title="Bike POS"
        description="Sell one or more motorcycles to a customer by chassis. Prices are VAT-inclusive; completing the sale marks the units sold and issues one branded invoice (with payment, a receipt)."
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
                No available bikes match. Assembled, reserved and unassembled units can all be sold.
              </div>
            ) : (
              <div className="max-h-[28rem] space-y-1.5 overflow-y-auto">
                {sellable.map((u) => {
                  const picked = inCart.has(u.id);
                  return (
                    <button
                      key={u.id}
                      onClick={() => toggle(u)}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm transition ${
                        picked
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
                      <span className="ml-auto flex shrink-0 items-center gap-2">
                        <AssemblyBadge unit={u} />
                        <span className="font-mono text-xs text-slate-600">
                          {formatMoney(Number(u.selling_price ?? 0), "ZMW")}
                        </span>
                        {picked
                          ? <Check className="h-4 w-4 text-brand-600" />
                          : <Plus className="h-4 w-4 text-slate-400" />}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Cart / sell panel */}
          <Card className="flex flex-col p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-800">Sale</span>
              {cart.length > 0 && (
                <span className="rounded-pill bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
                  {cart.length} bike{cart.length === 1 ? "" : "s"}
                </span>
              )}
            </div>
            {cart.length === 0 ? (
              <div className="flex-1 rounded-lg bg-slate-50 px-3 py-8 text-center text-sm text-slate-400">
                Add bikes from the left to build the sale.
              </div>
            ) : (
              <div className="flex-1 space-y-3">
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">Customer</span>
                  <select className={`${INPUT} w-full`} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                    <option value="">Walk-in customer</option>
                    {(customers.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </label>

                {/* Cart lines */}
                <div className="max-h-64 space-y-1.5 overflow-y-auto">
                  {cart.map((u) => (
                    <div key={u.id} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0">
                          <span className="block font-mono text-[13px] text-slate-800">{u.chassis_number}</span>
                          <span className="block truncate text-xs text-slate-500">{bikeLabel(u)}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-2">
                          <AssemblyBadge unit={u} />
                          <button onClick={() => remove(u.id)} title="Remove" className="text-slate-400 hover:text-red-600">
                            <X className="h-4 w-4" />
                          </button>
                        </span>
                      </div>
                      <label className="mt-1.5 flex items-center gap-2 text-xs text-slate-500">
                        Price (VAT-incl.)
                        <input
                          type="number" min={0}
                          className={`${INPUT} w-32 text-right`}
                          value={prices[u.id] ?? ""}
                          onChange={(e) => setPrices((p) => ({ ...p, [u.id]: e.target.value }))}
                        />
                      </label>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between border-t border-slate-200 pt-2 text-sm">
                  <span className="font-medium text-slate-700">Total</span>
                  <span className="font-mono font-semibold text-slate-900">{formatMoney(total, "ZMW")}</span>
                </div>

                {beforeAssembly && (
                  <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm">
                    <div className="flex items-start gap-2 font-medium text-amber-800">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>Some bikes in this sale aren't assembled yet — you're selling them before assembly.</span>
                    </div>
                    <label className="flex items-start gap-2 text-amber-900">
                      <input type="checkbox" className="mt-0.5" checked={assemblyRequired} onChange={(e) => setAssemblyRequired(e.target.checked)} />
                      <span>
                        We assemble them before delivery
                        <span className="block text-xs text-amber-700">
                          {assemblyRequired
                            ? "They'll be queued for assembly and can't be dispatched until assembled."
                            : "Reseller sale — delivered as-is; the buyer assembles them. Nothing is queued."}
                        </span>
                      </span>
                    </label>
                    <label className="flex items-start gap-2 text-amber-900">
                      <input type="checkbox" className="mt-0.5" checked={ackBeforeAssembly} onChange={(e) => setAckBeforeAssembly(e.target.checked)} />
                      <span>I confirm selling these bikes before they're assembled.</span>
                    </label>
                  </div>
                )}

                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={takePayment} onChange={(e) => setTakePayment(e.target.checked)} />
                  Take payment now
                </label>
                {takePayment && (
                  <div className="space-y-2">
                    <PaymentRows rows={payRows} onChange={setPayRows} fillAmount={total} fillLabel="Full total" />
                    <div className="flex justify-between text-xs text-slate-500">
                      <span>Collecting</span>
                      <span className="font-mono">{formatMoney(paidNum, "ZMW")} of {formatMoney(total, "ZMW")}</span>
                    </div>
                    {overpay ? (
                      <div className="text-sm text-red-600">Payments exceed the total.</div>
                    ) : total > 0 && paidNum > 0 && paidNum < total ? (
                      <div className="text-xs text-amber-600">
                        Balance {formatMoney(total - paidNum, "ZMW")} left outstanding — the invoice stays partially paid.
                      </div>
                    ) : null}
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
              {sell.isPending ? "Selling…" : takePayment && paidNum > 0 ? `Charge ${formatMoney(paidNum, "ZMW")}` : "Create invoice"}
            </Button>
          </Card>
        </div>
      )}

      {/* Completed sale */}
      {done && (
        <Card className="mx-auto mt-4 max-w-md p-5 text-sm">
          <div className="mb-2 flex items-center gap-2 text-emerald-700">
            <Check className="h-5 w-5" /><span className="font-semibold">
              {done.bikes.length} bike{done.bikes.length === 1 ? "" : "s"} sold
            </span>
          </div>
          <div className="mb-2 space-y-1 rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">
            {done.bikes.map((b) => (
              <div key={b.unit_id} className="flex items-center justify-between gap-2">
                <span className="font-mono text-[13px]">{b.chassis_number}</span>
                <span className="flex items-center gap-2">
                  {b.assembly_pending && <span className="text-xs text-orange-700">🟠 to assemble</span>}
                  <span className="font-mono">{formatMoney(b.price, "ZMW")}</span>
                </span>
              </div>
            ))}
          </div>
          <div className="flex justify-between"><span className="text-slate-500">Invoice</span>
            <span className="font-mono">{done.invoice.invoice_number}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Total</span>
            <span className="font-mono">{formatMoney(Number(done.invoice.grand_total_zmw ?? done.invoice.grand_total), "ZMW")}</span></div>
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
                      <td className="px-4 py-3 text-right font-mono font-medium text-slate-800">{formatMoney(s.revenue, "ZMW")}</td>
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
