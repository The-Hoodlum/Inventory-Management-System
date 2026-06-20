import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Field, emptyToNull, inputClass, toInt, toIntOrNull } from "@/components/form";
import { Button } from "@/components/ui";
import { catalogApi, type ProductInput } from "@/lib/catalog";
import { useSuppliers } from "@/lib/refdata";
import type { Criticality, Product, ProductStatus } from "@/types/api";

const UOM_SUGGESTIONS = ["pcs", "box", "carton", "set", "pair", "kg", "g", "litre", "ml", "meter", "roll"];
const CURRENCIES = ["USD", "ZMW", "CNY", "EUR", "GBP"];
const CRITICALITIES: Criticality[] = ["low", "medium", "high", "critical"];

interface FormState {
  sku: string;
  name: string;
  barcode: string;
  description: string;
  category: string;
  brand: string;
  primary_supplier_id: string;
  cost_price: string;
  selling_price: string;
  currency: string;
  unit_of_measure: string;
  units_per_carton: string;
  moq: string;
  lead_time_days: string;
  reorder_point: string;
  safety_stock: string;
  status: ProductStatus;
  // Intelligence profile
  commodity_tags: string; // comma-separated in the form
  country_of_origin: string;
  criticality: Criticality;
  strategic_item: boolean;
  alternate_supplier_available: boolean;
}

function initialState(p?: Product | null): FormState {
  return {
    sku: p?.sku ?? "",
    name: p?.name ?? "",
    barcode: p?.barcode ?? "",
    description: p?.description ?? "",
    category: p?.category_name ?? "",
    brand: p?.brand_name ?? "",
    primary_supplier_id: p?.primary_supplier_id ?? "",
    cost_price: p?.cost_price ?? "0",
    selling_price: p?.selling_price ?? "0",
    currency: p?.currency ?? "",
    unit_of_measure: p?.unit_of_measure ?? "",
    units_per_carton: String(p?.units_per_carton ?? 1),
    moq: String(p?.moq ?? 0),
    lead_time_days: String(p?.lead_time_days ?? 30),
    reorder_point: p?.reorder_point != null ? String(p.reorder_point) : "",
    safety_stock: p?.safety_stock != null ? String(p.safety_stock) : "",
    status: p?.status ?? "active",
    commodity_tags: (p?.commodity_tags ?? []).join(", "),
    country_of_origin: p?.country_of_origin ?? "",
    criticality: p?.criticality ?? "medium",
    strategic_item: p?.strategic_item ?? false,
    alternate_supplier_available: p?.alternate_supplier_available ?? false,
  };
}

function isNonNegNumber(v: string): boolean {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0;
}

export function ProductFormModal({
  mode,
  initial,
  onClose,
}: {
  mode: "create" | "edit";
  initial?: Product | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const { list: suppliers } = useSuppliers();
  const [form, setForm] = useState<FormState>(() => initialState(initial));
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["products"] });
    qc.invalidateQueries({ queryKey: ["ref", "products"] });
    qc.invalidateQueries({ queryKey: ["dashboard", "metrics"] });
  }

  const save = useMutation({
    mutationFn: () => {
      const body: ProductInput = {
        sku: form.sku.trim(),
        name: form.name.trim(),
        barcode: emptyToNull(form.barcode),
        description: emptyToNull(form.description),
        category: emptyToNull(form.category),
        brand: emptyToNull(form.brand),
        primary_supplier_id: form.primary_supplier_id || null,
        cost_price: form.cost_price.trim() || "0",
        selling_price: form.selling_price.trim() || "0",
        currency: form.currency || null,
        unit_of_measure: emptyToNull(form.unit_of_measure),
        units_per_carton: Math.max(1, toInt(form.units_per_carton, 1)),
        moq: Math.max(0, toInt(form.moq, 0)),
        lead_time_days: Math.max(0, toInt(form.lead_time_days, 0)),
        reorder_point: toIntOrNull(form.reorder_point),
        safety_stock: toIntOrNull(form.safety_stock),
        status: form.status,
        commodity_tags: form.commodity_tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        country_of_origin: emptyToNull(form.country_of_origin),
        criticality: form.criticality,
        strategic_item: form.strategic_item,
        alternate_supplier_available: form.alternate_supplier_available,
      };
      return mode === "create"
        ? catalogApi.createProduct(body)
        : catalogApi.updateProduct(initial!.id, body);
    },
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: () => catalogApi.deleteProduct(initial!.id),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const busy = save.isPending || remove.isPending;

  const submit = () => {
    if (!form.sku.trim()) return setErr("SKU is required.");
    if (!form.name.trim()) return setErr("Name is required.");
    if (!isNonNegNumber(form.cost_price)) return setErr("Cost must be a number ≥ 0.");
    if (!isNonNegNumber(form.selling_price)) return setErr("Price must be a number ≥ 0.");
    save.mutate();
  };

  const onDelete = () => {
    if (window.confirm("Delete this product? This cannot be undone.")) remove.mutate();
  };

  return (
    <Modal
      title={mode === "create" ? "New product" : "Edit product"}
      onClose={onClose}
      footer={
        <div className="flex w-full items-center justify-between">
          <div>
            {mode === "edit" && hasPermission("product.delete") && (
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
        <Field label="SKU" required>
          <input className={inputClass} value={form.sku} onChange={(e) => set("sku", e.target.value)} />
        </Field>
        <Field label="Barcode">
          <input className={inputClass} value={form.barcode} onChange={(e) => set("barcode", e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Name" required>
            <input className={inputClass} value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Description">
            <textarea
              className={inputClass}
              rows={2}
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </Field>
        </div>
        <Field label="Category" hint="Created if new">
          <input className={inputClass} value={form.category} onChange={(e) => set("category", e.target.value)} />
        </Field>
        <Field label="Brand" hint="Created if new">
          <input className={inputClass} value={form.brand} onChange={(e) => set("brand", e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Primary supplier">
            <select
              className={inputClass}
              value={form.primary_supplier_id}
              onChange={(e) => set("primary_supplier_id", e.target.value)}
            >
              <option value="">— None —</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Cost price">
          <input type="number" min={0} step="any" className={inputClass} value={form.cost_price} onChange={(e) => set("cost_price", e.target.value)} />
        </Field>
        <Field label="Selling price">
          <input type="number" min={0} step="any" className={inputClass} value={form.selling_price} onChange={(e) => set("selling_price", e.target.value)} />
        </Field>
        <Field label="Currency" hint="Blank = tenant default">
          <select className={inputClass} value={form.currency} onChange={(e) => set("currency", e.target.value)}>
            <option value="">— Tenant default —</option>
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Unit of measure">
          <input
            className={inputClass}
            list="uom-options"
            value={form.unit_of_measure}
            onChange={(e) => set("unit_of_measure", e.target.value)}
          />
          <datalist id="uom-options">
            {UOM_SUGGESTIONS.map((u) => (
              <option key={u} value={u} />
            ))}
          </datalist>
        </Field>
        <Field label="Units per carton">
          <input type="number" min={1} className={inputClass} value={form.units_per_carton} onChange={(e) => set("units_per_carton", e.target.value)} />
        </Field>
        <Field label="MOQ" hint="Minimum order quantity">
          <input type="number" min={0} className={inputClass} value={form.moq} onChange={(e) => set("moq", e.target.value)} />
        </Field>
        <Field label="Lead time (days)">
          <input type="number" min={0} className={inputClass} value={form.lead_time_days} onChange={(e) => set("lead_time_days", e.target.value)} />
        </Field>
        <Field label="Status">
          <select className={inputClass} value={form.status} onChange={(e) => set("status", e.target.value as ProductStatus)}>
            <option value="active">active</option>
            <option value="inactive">inactive</option>
            <option value="discontinued">discontinued</option>
          </select>
        </Field>
        <Field label="Reorder point" hint="Leave blank to auto-calculate">
          <input type="number" min={0} className={inputClass} value={form.reorder_point} onChange={(e) => set("reorder_point", e.target.value)} />
        </Field>
        <Field label="Safety stock" hint="Leave blank to auto-calculate">
          <input type="number" min={0} className={inputClass} value={form.safety_stock} onChange={(e) => set("safety_stock", e.target.value)} />
        </Field>

        {/* Intelligence profile */}
        <div className="sm:col-span-2 mt-1 border-t border-slate-200 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Intelligence profile
        </div>
        <div className="sm:col-span-2">
          <Field label="Commodity tags" hint="Comma-separated, e.g. steel, copper">
            <input className={inputClass} value={form.commodity_tags} onChange={(e) => set("commodity_tags", e.target.value)} />
          </Field>
        </div>
        <Field label="Country of origin" hint="ISO-2 or name">
          <input className={inputClass} value={form.country_of_origin} onChange={(e) => set("country_of_origin", e.target.value)} />
        </Field>
        <Field label="Criticality" hint="Stockout impact">
          <select
            className={inputClass}
            value={form.criticality}
            onChange={(e) => set("criticality", e.target.value as Criticality)}
          >
            {CRITICALITIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-300"
            checked={form.strategic_item}
            onChange={(e) => set("strategic_item", e.target.checked)}
          />
          Strategic item
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-300"
            checked={form.alternate_supplier_available}
            onChange={(e) => set("alternate_supplier_available", e.target.checked)}
          />
          Alternate supplier available
        </label>
      </div>
    </Modal>
  );
}
