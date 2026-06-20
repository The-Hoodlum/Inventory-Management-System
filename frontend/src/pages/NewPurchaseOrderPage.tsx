import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Field, emptyToNull, inputClass } from "@/components/form";
import { Button, Card } from "@/components/ui";
import { formatMoney } from "@/lib/format";
import { poApi, type POCreateInput } from "@/lib/po";
import { useProducts, useSuppliers, useWarehouses } from "@/lib/refdata";

interface LineState {
  key: number;
  productId: string;
  qty: string;
  unitCost: string;
}

function cartonsFor(qtyStr: string, upc: number | null | undefined): number | null {
  const q = Number(qtyStr);
  if (!Number.isFinite(q) || q <= 0 || !upc || upc <= 0) return null;
  return Math.ceil(q / upc);
}

export default function NewPurchaseOrderPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();

  const { list: suppliers, map: supplierMap } = useSuppliers();
  const { list: warehouses } = useWarehouses();
  const { list: products, map: productMap } = useProducts();

  const nextKey = useRef(2);
  const [supplierId, setSupplierId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [currency, setCurrency] = useState("");
  const [expectedDate, setExpectedDate] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineState[]>([
    { key: 1, productId: "", qty: "", unitCost: "" },
  ]);
  const [err, setErr] = useState<string | null>(null);

  const updateLine = (key: number, patch: Partial<LineState>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const removeLine = (key: number) => setLines((ls) => ls.filter((l) => l.key !== key));
  const addLine = () =>
    setLines((ls) => [...ls, { key: nextKey.current++, productId: "", qty: "", unitCost: "" }]);

  const onSupplier = (id: string) => {
    setSupplierId(id);
    const s = supplierMap.get(id);
    if (s) setCurrency(s.currency);
  };

  const onProduct = (key: number, productId: string) => {
    const p = productMap.get(productId);
    updateLine(key, { productId, unitCost: p ? p.cost_price : "" });
  };

  const cur = currency.trim() || "USD";
  const subtotal = lines.reduce((sum, l) => {
    const q = Number(l.qty);
    const c = Number(l.unitCost);
    return sum + (Number.isFinite(q) && Number.isFinite(c) && q > 0 ? q * c : 0);
  }, 0);

  const create = useMutation({
    mutationFn: () => {
      const valid = lines.filter((l) => l.productId && Number(l.qty) > 0);
      const body: POCreateInput = {
        supplier_id: supplierId,
        warehouse_id: warehouseId,
        currency: currency.trim() ? currency.trim().toUpperCase() : null,
        expected_date: expectedDate || null,
        notes: emptyToNull(notes),
        lines: valid.map((l) => {
          const upc = productMap.get(l.productId)?.units_per_carton ?? null;
          return {
            product_id: l.productId,
            ordered_qty: l.qty.trim(),
            unit_cost: l.unitCost.trim() || "0",
            units_per_carton: upc,
            ordered_cartons: cartonsFor(l.qty, upc),
          };
        }),
      };
      return poApi.create(body);
    },
    onSuccess: (po) => {
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "metrics"] });
      navigate(`/purchase-orders/${po.id}`);
    },
    onError: (e) => setErr((e as Error).message),
  });

  const submit = () => {
    if (!supplierId) return setErr("Select a supplier.");
    if (!warehouseId) return setErr("Select a warehouse.");
    const valid = lines.filter((l) => l.productId && Number(l.qty) > 0);
    if (valid.length === 0) return setErr("Add at least one line with a product and quantity.");
    for (const l of valid) {
      const c = Number(l.unitCost);
      if (!Number.isFinite(c) || c < 0) return setErr("Unit cost must be a number ≥ 0 on every line.");
    }
    setErr(null);
    create.mutate();
  };

  if (!hasPermission("po.create")) {
    return (
      <div>
        <PageHeader title="New purchase order" />
        <Card className="p-6 text-sm text-slate-500">
          You don’t have permission to create purchase orders.
        </Card>
      </div>
    );
  }

  return (
    <div>
      <Link
        to="/purchase-orders"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" /> Purchase orders
      </Link>

      <PageHeader
        title="New purchase order"
        description="Create a draft you can review, submit and approve."
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => navigate("/purchase-orders")} disabled={create.isPending}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={create.isPending}>
              {create.isPending ? "Saving…" : "Save draft"}
            </Button>
          </div>
        }
      />

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {err}
        </div>
      )}

      <Card className="mb-4 p-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Supplier" required>
            <select className={inputClass} value={supplierId} onChange={(e) => onSupplier(e.target.value)}>
              <option value="">Select…</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Warehouse" required>
            <select
              className={inputClass}
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
            >
              <option value="">Select…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Currency" hint="Defaults from the supplier">
            <input
              className={inputClass}
              maxLength={3}
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              placeholder="USD"
            />
          </Field>
          <Field label="Expected date">
            <input
              type="date"
              className={inputClass}
              value={expectedDate}
              onChange={(e) => setExpectedDate(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4">
          <Field label="Notes">
            <textarea
              className={inputClass}
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional notes for this order"
            />
          </Field>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">Line items</h2>
          <Button variant="secondary" onClick={addLine}>
            <Plus className="h-4 w-4" /> Add line
          </Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Product</th>
                <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                <th className="px-4 py-2.5 text-right font-medium">Unit cost</th>
                <th className="px-4 py-2.5 text-right font-medium">Cartons</th>
                <th className="px-4 py-2.5 text-right font-medium">Line total</th>
                <th className="w-10 px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {lines.map((l) => {
                const product = productMap.get(l.productId);
                const upc = product?.units_per_carton ?? null;
                const cartons = cartonsFor(l.qty, upc);
                const q = Number(l.qty);
                const c = Number(l.unitCost);
                const lineTotal = Number.isFinite(q) && Number.isFinite(c) && q > 0 ? q * c : 0;
                const belowMoq =
                  product && product.moq > 0 && Number.isFinite(q) && q > 0 && q < product.moq;
                return (
                  <tr key={l.key} className="align-top">
                    <td className="px-4 py-3">
                      <select
                        className={inputClass}
                        value={l.productId}
                        onChange={(e) => onProduct(l.key, e.target.value)}
                      >
                        <option value="">Select product…</option>
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.sku} — {p.name}
                          </option>
                        ))}
                      </select>
                      {product && (
                        <div className="mt-1 text-xs text-slate-400">
                          {upc ? `${upc}/carton` : "no carton size"}
                          {product.moq > 0 ? ` · MOQ ${product.moq}` : ""}
                          {belowMoq && <span className="text-amber-600"> · below MOQ</span>}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <input
                        type="number"
                        min={0}
                        step="any"
                        className={`${inputClass} w-24 text-right`}
                        value={l.qty}
                        onChange={(e) => updateLine(l.key, { qty: e.target.value })}
                      />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <input
                        type="number"
                        min={0}
                        step="any"
                        className={`${inputClass} w-28 text-right`}
                        value={l.unitCost}
                        onChange={(e) => updateLine(l.key, { unitCost: e.target.value })}
                      />
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                      {cartons ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-800">
                      {formatMoney(lineTotal, cur)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => removeLine(l.key)}
                        disabled={lines.length === 1}
                        className="text-slate-400 hover:text-red-600 disabled:opacity-30"
                        aria-label="Remove line"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-200 text-sm font-semibold">
                <td className="px-4 py-3 text-slate-700" colSpan={4}>
                  Total
                </td>
                <td className="px-4 py-3 text-right font-mono">{formatMoney(subtotal, cur)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>
    </div>
  );
}
