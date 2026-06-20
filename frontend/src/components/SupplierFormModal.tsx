import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Field, emptyToNull, inputClass, toInt } from "@/components/form";
import { Button } from "@/components/ui";
import { catalogApi, type SupplierInput } from "@/lib/catalog";
import type { Supplier, SupplierStatus } from "@/types/api";

interface FormState {
  name: string;
  contact_person: string;
  email: string;
  phone: string;
  country: string;
  currency: string;
  payment_terms: string;
  default_lead_time_days: string;
  status: SupplierStatus;
}

function initialState(s?: Supplier | null): FormState {
  return {
    name: s?.name ?? "",
    contact_person: s?.contact_person ?? "",
    email: s?.email ?? "",
    phone: s?.phone ?? "",
    country: s?.country ?? "",
    currency: s?.currency ?? "USD",
    payment_terms: s?.payment_terms ?? "",
    default_lead_time_days: String(s?.default_lead_time_days ?? 30),
    status: s?.status ?? "active",
  };
}

export function SupplierFormModal({
  mode,
  initial,
  onClose,
}: {
  mode: "create" | "edit";
  initial?: Supplier | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const [form, setForm] = useState<FormState>(() => initialState(initial));
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["suppliers"] });
    qc.invalidateQueries({ queryKey: ["ref", "suppliers"] });
    qc.invalidateQueries({ queryKey: ["dashboard", "metrics"] });
  }

  const save = useMutation({
    mutationFn: () => {
      const body: SupplierInput = {
        name: form.name.trim(),
        contact_person: emptyToNull(form.contact_person),
        email: emptyToNull(form.email),
        phone: emptyToNull(form.phone),
        country: emptyToNull(form.country),
        currency: form.currency.trim().toUpperCase(),
        payment_terms: emptyToNull(form.payment_terms),
        default_lead_time_days: toInt(form.default_lead_time_days, 30),
        status: form.status,
      };
      return mode === "create"
        ? catalogApi.createSupplier(body)
        : catalogApi.updateSupplier(initial!.id, body);
    },
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: () => catalogApi.deleteSupplier(initial!.id),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const busy = save.isPending || remove.isPending;

  const submit = () => {
    if (!form.name.trim()) return setErr("Name is required.");
    if (form.currency.trim().length !== 3) return setErr("Currency must be a 3-letter code (e.g. USD).");
    save.mutate();
  };

  const onDelete = () => {
    if (window.confirm("Delete this supplier? This cannot be undone.")) remove.mutate();
  };

  return (
    <Modal
      title={mode === "create" ? "New supplier" : "Edit supplier"}
      onClose={onClose}
      footer={
        <div className="flex w-full items-center justify-between">
          <div>
            {mode === "edit" && hasPermission("supplier.update") && (
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
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Name" required>
            <input className={inputClass} value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
        </div>
        <Field label="Contact person">
          <input
            className={inputClass}
            value={form.contact_person}
            onChange={(e) => set("contact_person", e.target.value)}
          />
        </Field>
        <Field label="Email">
          <input
            type="email"
            className={inputClass}
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
          />
        </Field>
        <Field label="Phone">
          <input className={inputClass} value={form.phone} onChange={(e) => set("phone", e.target.value)} />
        </Field>
        <Field label="Country">
          <input
            className={inputClass}
            value={form.country}
            onChange={(e) => set("country", e.target.value)}
          />
        </Field>
        <Field label="Currency" hint="3-letter code">
          <input
            className={inputClass}
            maxLength={3}
            value={form.currency}
            onChange={(e) => set("currency", e.target.value)}
          />
        </Field>
        <Field label="Default lead time (days)">
          <input
            type="number"
            min={0}
            className={inputClass}
            value={form.default_lead_time_days}
            onChange={(e) => set("default_lead_time_days", e.target.value)}
          />
        </Field>
        <Field label="Payment terms">
          <input
            className={inputClass}
            value={form.payment_terms}
            onChange={(e) => set("payment_terms", e.target.value)}
            placeholder="e.g. Net 30"
          />
        </Field>
        <Field label="Status">
          <select
            className={inputClass}
            value={form.status}
            onChange={(e) => set("status", e.target.value as SupplierStatus)}
          >
            <option value="active">active</option>
            <option value="inactive">inactive</option>
          </select>
        </Field>
      </div>
    </Modal>
  );
}
