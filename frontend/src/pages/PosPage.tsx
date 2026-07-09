import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { SellBikeModal } from "@/components/SellBikeModal";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { formatMoney } from "@/lib/format";
import { useBranches, useWarehouses } from "@/lib/refdata";
import { PAYMENT_METHODS, type PaymentMethod, type Receipt, salesApi } from "@/lib/sales";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

interface CartLine {
  product_id: string;
  sku: string;
  name: string;
  qty: number;
  unit_price: number;
}

export default function PosPage() {
  const warehouses = useWarehouses();
  const branches = useBranches();
  const locLabel = (w: { name: string; branch_id: string | null }) => {
    const b = w.branch_id ? branches.map.get(w.branch_id) : undefined;
    return b ? `${b.name} · ${w.name}` : w.name;
  };
  const [locationId, setLocationId] = useState("");
  const [search, setSearch] = useState("");
  const [cart, setCart] = useState<CartLine[]>([]);
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [tendered, setTendered] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { hasPermission } = useAuth();
  const [showSellBike, setShowSellBike] = useState(false);

  const location = locationId || warehouses.list[0]?.id || "";

  const term = search.trim();
  const searchQ = useQuery({
    queryKey: ["pos-search", term],
    queryFn: () => catalogApi.products({ search: term, page: 1, page_size: 8 }),
    enabled: term.length >= 2,
    placeholderData: (prev) => prev,
  });
  const inCart = new Set(cart.map((l) => l.product_id));
  const matches = (searchQ.data?.items ?? []).filter((p) => !inCart.has(p.id)).slice(0, 8);

  const total = useMemo(() => cart.reduce((s, l) => s + l.qty * l.unit_price, 0), [cart]);
  const pay = Number(tendered) || total;
  const change = Math.max(0, pay - total);

  const checkout = useMutation({
    mutationFn: () =>
      salesApi.posCheckout({
        location_id: location,
        lines: cart.map((l) => ({ product_id: l.product_id, qty: l.qty, unit_price: l.unit_price })),
        // POS settles exactly the sale total (any tendered surplus is change).
        payments: [{ method, amount: total }],
      }),
    onSuccess: (res) => {
      setReceipt(res.receipt);
      setCart([]);
      setTendered("");
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Checkout failed."),
  });

  function add(p: { id: string; sku: string; name: string; selling_price?: number | string }) {
    setCart((c) => [
      ...c,
      { product_id: p.id, sku: p.sku, name: p.name, qty: 1, unit_price: Number(p.selling_price ?? 0) },
    ]);
    setSearch("");
  }
  const setLine = (i: number, patch: Partial<CartLine>) =>
    setCart((c) => c.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  return (
    <div>
      <PageHeader
        title="Point of Sale"
        description="Fast cash sale — deducts stock from the selected location immediately."
        actions={hasPermission("motorcycle.manage") ? (
          <Button variant="secondary" onClick={() => setShowSellBike(true)}>Sell a bike</Button>
        ) : undefined}
      />
      {showSellBike && <SellBikeModal onClose={() => setShowSellBike(false)} />}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* Catalog / search */}
        <Card className="p-4">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <label className="text-sm text-slate-500">Location</label>
            <select value={location} onChange={(e) => setLocationId(e.target.value)} className={INPUT}>
              {warehouses.list.map((w) => (
                <option key={w.id} value={w.id}>{locLabel(w)}</option>
              ))}
            </select>
          </div>
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Scan or search product (name / SKU)" className={`${INPUT} w-full`} autoFocus />
          {term.length >= 2 && (
            <div className="mt-1 max-h-72 overflow-y-auto rounded-lg border border-slate-200">
              {searchQ.isFetching && matches.length === 0 ? (
                <div className="p-3"><Spinner label="Searching…" /></div>
              ) : matches.length === 0 ? (
                <div className="p-3 text-sm text-slate-400">No matching items.</div>
              ) : (
                matches.map((p) => (
                  <button key={p.id} onClick={() => add(p)}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50">
                    <span>
                      <span className="font-medium text-slate-800">{p.name}</span>
                      <span className="ml-2 font-mono text-xs text-slate-400">{p.sku}</span>
                    </span>
                    <span className="flex items-center gap-2 text-xs text-slate-500">
                      {formatMoney(Number(p.selling_price ?? 0))}
                      <Plus className="h-3.5 w-3.5 text-brand-600" />
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </Card>

        {/* Cart + payment */}
        <Card className="flex flex-col p-4">
          <div className="mb-2 text-sm font-semibold text-slate-800">Cart</div>
          {cart.length === 0 ? (
            <div className="flex-1 rounded-lg bg-slate-50 px-3 py-8 text-center text-sm text-slate-400">
              Add products to start a sale.
            </div>
          ) : (
            <div className="flex-1 space-y-2">
              {cart.map((l, i) => (
                <div key={l.product_id} className="flex items-center gap-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-800">{l.name}</div>
                    <div className="font-mono text-xs text-slate-400">{l.sku}</div>
                  </div>
                  <input type="number" min={1} value={l.qty}
                    onChange={(e) => setLine(i, { qty: Math.max(1, Number(e.target.value)) })}
                    className={`${INPUT} w-14 text-right`} />
                  <input type="number" min={0} value={l.unit_price}
                    onChange={(e) => setLine(i, { unit_price: Number(e.target.value) })}
                    className={`${INPUT} w-20 text-right`} />
                  <div className="w-20 text-right font-mono text-slate-700">{formatMoney(l.qty * l.unit_price)}</div>
                  <button onClick={() => setCart((c) => c.filter((_, j) => j !== i))}
                    className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          )}

          <div className="mt-3 border-t border-slate-200 pt-3">
            <div className="flex items-center justify-between text-lg font-semibold text-slate-900">
              <span>Total</span><span className="font-mono">{formatMoney(total)}</span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)} className={INPUT}>
                {PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              <input type="number" min={0} value={tendered} onChange={(e) => setTendered(e.target.value)}
                placeholder={`Tendered (${formatMoney(total)})`} className={`${INPUT} text-right`} />
            </div>
            {method === "cash" && pay > total && (
              <div className="mt-1 text-right text-sm text-emerald-700">Change: {formatMoney(change)}</div>
            )}
            {err && <div className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
            <Button className="mt-3 w-full justify-center"
              disabled={cart.length === 0 || !location || checkout.isPending}
              onClick={() => { setErr(null); checkout.mutate(); }}>
              {checkout.isPending ? "Processing…" : `Charge ${formatMoney(total)}`}
            </Button>
          </div>
        </Card>
      </div>

      {/* Receipt */}
      {receipt && (
        <Card className="mx-auto mt-4 max-w-md p-5 text-sm">
          <div className="mb-2 flex items-center gap-2 text-emerald-700">
            <Check className="h-5 w-5" /><span className="font-semibold">Sale complete</span>
          </div>
          <div className="flex justify-between"><span className="text-slate-500">Receipt</span>
            <span className="font-mono font-medium">{receipt.receipt_number}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Invoice</span>
            <span className="font-mono">{receipt.invoice_number}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Paid</span>
            <span className="font-mono">{formatMoney(receipt.amount_paid)}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Balance</span>
            <span className="font-mono">{formatMoney(receipt.balance)}</span></div>
          <Button variant="secondary" className="mt-3 w-full justify-center" onClick={() => setReceipt(null)}>
            New sale
          </Button>
        </Card>
      )}
    </div>
  );
}
