import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "@/components/Modal";
import { Field, inputClass } from "@/components/form";
import { Button } from "@/components/ui";
import { formatQty } from "@/lib/format";
import { inventoryApi } from "@/lib/inventory";

const REASON_CODES = [
  "Stock count correction",
  "Damage / write-off",
  "Found stock",
  "Data correction",
  "Other",
];

export function AdjustStockModal({
  productId,
  warehouseId,
  productLabel,
  warehouseLabel,
  currentOnHand,
  onClose,
}: {
  productId: string;
  warehouseId: string;
  productLabel: string;
  warehouseLabel: string;
  currentOnHand: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [reasonCode, setReasonCode] = useState(REASON_CODES[0]);
  const [note, setNote] = useState("");
  const [delta, setDelta] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const deltaNum = Number(delta);
  const resulting = Number(currentOnHand) + (Number.isFinite(deltaNum) ? deltaNum : 0);

  const adjust = useMutation({
    mutationFn: () =>
      inventoryApi.adjust({
        warehouse_id: warehouseId,
        product_id: productId,
        delta: delta.trim(),
        reason: note.trim() ? `${reasonCode}: ${note.trim()}` : reasonCode,
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
    if (!Number.isFinite(deltaNum) || deltaNum === 0)
      return setErr("Enter a non-zero adjustment (negative to reduce stock).");
    if (resulting < 0) return setErr("Adjustment would take on-hand below zero.");
    setErr(null);
    adjust.mutate();
  };

  return (
    <Modal
      title="Adjust stock"
      onClose={onClose}
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={adjust.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={adjust.isPending}>
            {adjust.isPending ? "Applying…" : "Apply adjustment"}
          </Button>
        </>
      }
    >
      {err && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}
      <div className="mb-4 rounded-lg bg-slate-50 px-3 py-2 text-sm">
        <div className="font-medium text-slate-800">{productLabel}</div>
        <div className="text-slate-500">
          {warehouseLabel} · on hand {formatQty(currentOnHand)}
        </div>
      </div>
      <div className="space-y-4">
        <Field label="Reason">
          <select
            className={inputClass}
            value={reasonCode}
            onChange={(e) => setReasonCode(e.target.value)}
          >
            {REASON_CODES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Adjustment (+/-)" hint="Use a negative number to reduce stock">
          <input
            type="number"
            step="any"
            className={inputClass}
            value={delta}
            onChange={(e) => setDelta(e.target.value)}
            placeholder="e.g. -3"
          />
        </Field>
        <div className="text-sm text-slate-500">
          New on hand:{" "}
          <span className="font-mono font-medium text-slate-800">{formatQty(resulting)}</span>
        </div>
        <Field label="Note">
          <textarea
            className={inputClass}
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional detail for the audit trail"
          />
        </Field>
      </div>
    </Modal>
  );
}
