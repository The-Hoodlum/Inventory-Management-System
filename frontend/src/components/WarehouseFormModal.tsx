import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Field, emptyToNull, inputClass } from "@/components/form";
import { Button } from "@/components/ui";
import { catalogApi, type WarehouseInput } from "@/lib/catalog";
import type { Warehouse } from "@/types/api";

interface FormState {
  code: string;
  name: string;
  address: string;
  is_active: boolean;
}

export function WarehouseFormModal({
  mode,
  initial,
  onClose,
}: {
  mode: "create" | "edit";
  initial?: Warehouse | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const [form, setForm] = useState<FormState>(() => ({
    code: initial?.code ?? "",
    name: initial?.name ?? "",
    address: initial?.address ?? "",
    is_active: initial?.is_active ?? true,
  }));
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["warehouses-page"] });
    qc.invalidateQueries({ queryKey: ["ref", "warehouses"] });
    qc.invalidateQueries({ queryKey: ["dashboard", "metrics"] });
  }

  const save = useMutation({
    mutationFn: () => {
      const body: WarehouseInput = {
        code: form.code.trim(),
        name: form.name.trim(),
        address: emptyToNull(form.address),
        is_active: form.is_active,
      };
      return mode === "create"
        ? catalogApi.createWarehouse(body)
        : catalogApi.updateWarehouse(initial!.id, body);
    },
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: () => catalogApi.deleteWarehouse(initial!.id),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const busy = save.isPending || remove.isPending;

  const submit = () => {
    if (!form.code.trim()) return setErr("Code is required.");
    if (!form.name.trim()) return setErr("Name is required.");
    save.mutate();
  };

  const onDelete = () => {
    if (window.confirm("Delete this warehouse? This cannot be undone.")) remove.mutate();
  };

  return (
    <Modal
      title={mode === "create" ? "New warehouse" : "Edit warehouse"}
      onClose={onClose}
      size="md"
      footer={
        <div className="flex w-full items-center justify-between">
          <div>
            {mode === "edit" && hasPermission("warehouse.manage") && (
              <Button
                variant="ghost"
                className="text-red-600 hover:bg-red-50"
                disabled={busy}
                onClick={onDelete}
              >
                Delete
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={busy}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      }
    >
      {err && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}
      <div className="space-y-4">
        <Field label="Code" required hint="Short identifier, e.g. WH-MAIN">
          <input className={inputClass} value={form.code} onChange={(e) => set("code", e.target.value)} />
        </Field>
        <Field label="Name" required>
          <input className={inputClass} value={form.name} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Address">
          <input
            className={inputClass}
            value={form.address}
            onChange={(e) => set("address", e.target.value)}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => set("is_active", e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
          Active
        </label>
      </div>
    </Modal>
  );
}
