import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useState } from "react";

import { Modal } from "@/components/Modal";
import { Field, emptyToNull, inputClass } from "@/components/form";
import { Button } from "@/components/ui";
import { inventoryApi } from "@/lib/inventory";
import { useProducts, useWarehouses } from "@/lib/refdata";

export function TransferStockModal({
  defaultProductId,
  defaultFromWarehouseId,
  onClose,
}: {
  defaultProductId?: string;
  defaultFromWarehouseId?: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { list: products } = useProducts();
  const { list: warehouses } = useWarehouses();

  const [productId, setProductId] = useState(defaultProductId ?? "");
  const [fromId, setFromId] = useState(defaultFromWarehouseId ?? "");
  const [toId, setToId] = useState("");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const transfer = useMutation({
    mutationFn: () =>
      inventoryApi.transfer({
        product_id: productId,
        from_warehouse_id: fromId,
        to_warehouse_id: toId,
        quantity: qty.trim(),
        reason: emptyToNull(reason),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["movements"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "metrics"] });
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const submit = () => {
    if (!productId) return setErr("Select a product.");
    if (!fromId || !toId) return setErr("Select both source and destination warehouses.");
    if (fromId === toId) return setErr("Source and destination must be different.");
    if (!(Number(qty) > 0)) return setErr("Quantity must be greater than zero.");
    setErr(null);
    transfer.mutate();
  };

  return (
    <Modal
      title="Transfer stock"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={transfer.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={transfer.isPending}>
            {transfer.isPending ? "Transferring…" : "Transfer"}
          </Button>
        </>
      }
    >
      {err && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}
      <div className="space-y-4">
        <Field label="Product" required>
          <select className={inputClass} value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">Select product…</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} — {p.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[1fr_auto_1fr]">
          <Field label="From" required>
            <select className={inputClass} value={fromId} onChange={(e) => setFromId(e.target.value)}>
              <option value="">Select…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="hidden pb-2 text-slate-400 sm:block">
            <ArrowRight className="h-4 w-4" />
          </div>
          <Field label="To" required>
            <select className={inputClass} value={toId} onChange={(e) => setToId(e.target.value)}>
              <option value="">Select…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Quantity" required>
          <input
            type="number"
            min={0}
            step="any"
            className={inputClass}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </Field>
        <Field label="Reason">
          <input
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Optional"
          />
        </Field>
      </div>
    </Modal>
  );
}
