// Motorcycle setup — the tenant-configurable reference catalog (Models / Variants /
// Colours). Each tab is a shared DataTable with a create/edit modal, so admins configure
// the module (nothing is hard-coded). Gated on motorcycle.config.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bike } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, DataTable, PageHeading, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { clsx } from "clsx";
import { ApiError } from "@/lib/api";
import {
  type MotoColour,
  type MotoModel,
  type MotoVariant,
  type ReorderPoint,
  motorcyclesApi,
  useMotoColours,
  useMotoModels,
} from "@/lib/motorcycles";

type Tab = "models" | "variants" | "colours" | "reorder points";
const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function MotorcycleSetupPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("models");
  return (
    <div>
      <PageHeading
        title="Motorcycle setup"
        description="Configure the reference catalog: models, variants, colours and stock reorder points."
        icon={<Bike className="h-5 w-5" />}
        actions={<Button variant="secondary" onClick={() => navigate("/motorcycles")}>Back to units</Button>}
      />
      <div className="mb-4 flex gap-1 border-b border-line">
        {(["models", "variants", "colours", "reorder points"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={clsx("-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize transition",
              tab === t ? "border-brand-600 text-brand-700" : "border-transparent text-muted hover:text-content")}>
            {t}
          </button>
        ))}
      </div>
      {tab === "models" && <ModelsTab />}
      {tab === "variants" && <VariantsTab />}
      {tab === "colours" && <ColoursTab />}
      {tab === "reorder points" && <ReorderPointsTab />}
    </div>
  );
}

function useCrud(key: string, queryFn: () => Promise<{ items: unknown[]; total: number }>) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["moto", key], queryFn });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["moto", key] });
  return { q, invalidate };
}

// --------------------------------- models ---------------------------------
function ModelsTab() {
  const [table, setTable] = useState<DataTableState>(initialTableState(20));
  const { q, invalidate } = useCrud("setup-models", () => motorcyclesApi.listModels());
  const [modal, setModal] = useState<{ item?: MotoModel } | null>(null);

  const columns: Column<MotoModel>[] = [
    { key: "name", header: "Model", accessor: (m) => m.name, className: "font-medium text-content" },
    { key: "brand", header: "Brand", accessor: (m) => m.brand_name ?? "—" },
    { key: "cc", header: "Engine cc", align: "right", accessor: (m) => m.engine_cc ?? "—" },
    { key: "price", header: "Default price", align: "right", accessor: (m) => m.default_selling_price ?? "—" },
    { key: "status", header: "Status", accessor: (m) => (m.is_active ? "active" : "inactive"), render: (m) => <StatusBadge status={m.is_active ? "active" : "inactive"} /> },
    { key: "actions", header: "", align: "right", render: (m) => <Button variant="ghost" onClick={() => setModal({ item: m })}>Edit</Button> },
  ];
  const items = (q.data?.items ?? []) as MotoModel[];

  return (
    <>
      <div className="mb-3 flex justify-end"><Button onClick={() => setModal({})}>New model</Button></div>
      <DataTable<MotoModel> columns={columns} rows={items} total={q.data?.total ?? 0} rowId={(m) => m.id}
        state={table} onStateChange={setTable} loading={q.isLoading} searchable={false}
        storageKey="moto-models" exportName="motorcycle-models" emptyTitle="No models yet" />
      {modal && <ModelModal item={modal.item} onClose={() => setModal(null)} onDone={() => { setModal(null); void invalidate(); }} />}
    </>
  );
}

function ModelModal({ item, onClose, onDone }: { item?: MotoModel; onClose: () => void; onDone: () => void }) {
  const models = useMotoModels();
  const brandSuggestions = [...new Set((models.data?.items ?? []).map((m) => m.brand_name).filter(Boolean))] as string[];
  const [name, setName] = useState(item?.name ?? "");
  const [brand, setBrand] = useState(item?.brand_name ?? "");
  const [cc, setCc] = useState(item?.engine_cc?.toString() ?? "");
  const [price, setPrice] = useState(item?.default_selling_price?.toString() ?? "");
  const [active, setActive] = useState(item?.is_active ?? true);
  const [err, setErr] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { name, engine_cc: cc ? Number(cc) : null, default_selling_price: price ? Number(price) : null, is_active: active };
      if (item) return motorcyclesApi.updateModel(item.id, body);
      return motorcyclesApi.createModel({ ...body, brand });
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the model."),
  });
  const canSave = name.trim() && (item || brand.trim());

  return (
    <Modal title={item ? "Edit model" : "New model"} size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!canSave || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Save"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <Field label="Model name *"><input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        {!item && (
          <Field label="Brand *">
            <input className={INPUT} value={brand} onChange={(e) => setBrand(e.target.value)} list="moto-brands" placeholder="Existing or new brand" />
            <datalist id="moto-brands">{brandSuggestions.map((b) => <option key={b} value={b} />)}</datalist>
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Engine cc"><input type="number" className={INPUT} value={cc} onChange={(e) => setCc(e.target.value)} /></Field>
          <Field label="Default price"><input type="number" min={0} className={INPUT} value={price} onChange={(e) => setPrice(e.target.value)} /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-content"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active</label>
      </div>
    </Modal>
  );
}

// -------------------------------- variants --------------------------------
function VariantsTab() {
  const [table, setTable] = useState<DataTableState>(initialTableState(20));
  const { q, invalidate } = useCrud("setup-variants", () => motorcyclesApi.listVariants());
  const [modal, setModal] = useState<{ item?: MotoVariant } | null>(null);

  const columns: Column<MotoVariant>[] = [
    { key: "name", header: "Variant", accessor: (v) => v.name, className: "font-medium text-content" },
    { key: "model", header: "Model", accessor: (v) => v.model_name ?? "—" },
    { key: "status", header: "Status", accessor: (v) => (v.is_active ? "active" : "inactive"), render: (v) => <StatusBadge status={v.is_active ? "active" : "inactive"} /> },
    { key: "actions", header: "", align: "right", render: (v) => <Button variant="ghost" onClick={() => setModal({ item: v })}>Edit</Button> },
  ];
  const items = (q.data?.items ?? []) as MotoVariant[];

  return (
    <>
      <div className="mb-3 flex justify-end"><Button onClick={() => setModal({})}>New variant</Button></div>
      <DataTable<MotoVariant> columns={columns} rows={items} total={q.data?.total ?? 0} rowId={(v) => v.id}
        state={table} onStateChange={setTable} loading={q.isLoading} searchable={false}
        storageKey="moto-variants" exportName="motorcycle-variants" emptyTitle="No variants yet" />
      {modal && <VariantModal item={modal.item} onClose={() => setModal(null)} onDone={() => { setModal(null); void invalidate(); }} />}
    </>
  );
}

function VariantModal({ item, onClose, onDone }: { item?: MotoVariant; onClose: () => void; onDone: () => void }) {
  const models = useMotoModels();
  const [name, setName] = useState(item?.name ?? "");
  const [modelId, setModelId] = useState(item?.model_id ?? "");
  const [active, setActive] = useState(item?.is_active ?? true);
  const [err, setErr] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: () => {
      if (item) return motorcyclesApi.updateVariant(item.id, { name, is_active: active });
      return motorcyclesApi.createVariant({ model_id: modelId, name, is_active: active });
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the variant."),
  });
  const canSave = name.trim() && (item || modelId);

  return (
    <Modal title={item ? "Edit variant" : "New variant"} size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!canSave || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Save"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        {!item && (
          <Field label="Model *">
            <select className={INPUT} value={modelId} onChange={(e) => setModelId(e.target.value)}>
              <option value="">Select a model…</option>
              {(models.data?.items ?? []).map((mm) => <option key={mm.id} value={mm.id}>{mm.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Variant name *"><input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <label className="flex items-center gap-2 text-sm text-content"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active</label>
      </div>
    </Modal>
  );
}

// --------------------------------- colours --------------------------------
function ColoursTab() {
  const [table, setTable] = useState<DataTableState>(initialTableState(20));
  const { q, invalidate } = useCrud("setup-colours", () => motorcyclesApi.listColours());
  const [modal, setModal] = useState<{ item?: MotoColour } | null>(null);

  const columns: Column<MotoColour>[] = [
    { key: "name", header: "Colour", accessor: (c) => c.name, className: "font-medium text-content",
      render: (c) => (
        <span className="inline-flex items-center gap-2">
          {c.hex_code && <span className="h-3.5 w-3.5 rounded-full border border-line" style={{ backgroundColor: c.hex_code }} />}
          {c.name}
        </span>
      ) },
    { key: "hex", header: "Hex", accessor: (c) => c.hex_code ?? "—", className: "font-mono text-[13px]" },
    { key: "status", header: "Status", accessor: (c) => (c.is_active ? "active" : "inactive"), render: (c) => <StatusBadge status={c.is_active ? "active" : "inactive"} /> },
    { key: "actions", header: "", align: "right", render: (c) => <Button variant="ghost" onClick={() => setModal({ item: c })}>Edit</Button> },
  ];
  const items = (q.data?.items ?? []) as MotoColour[];

  return (
    <>
      <div className="mb-3 flex justify-end"><Button onClick={() => setModal({})}>New colour</Button></div>
      <DataTable<MotoColour> columns={columns} rows={items} total={q.data?.total ?? 0} rowId={(c) => c.id}
        state={table} onStateChange={setTable} loading={q.isLoading} searchable={false}
        storageKey="moto-colours" exportName="motorcycle-colours" emptyTitle="No colours yet" />
      {modal && <ColourModal item={modal.item} onClose={() => setModal(null)} onDone={() => { setModal(null); void invalidate(); }} />}
    </>
  );
}

function ColourModal({ item, onClose, onDone }: { item?: MotoColour; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(item?.name ?? "");
  const [hex, setHex] = useState(item?.hex_code ?? "");
  const [active, setActive] = useState(item?.is_active ?? true);
  const [err, setErr] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: () => {
      const body = { name, hex_code: hex || null, is_active: active };
      if (item) return motorcyclesApi.updateColour(item.id, body);
      return motorcyclesApi.createColour(body);
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the colour."),
  });

  return (
    <Modal title={item ? "Edit colour" : "New colour"} size="sm" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!name.trim() || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Save"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <Field label="Colour name *"><input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Hex code">
          <div className="flex items-center gap-2">
            <input className={INPUT} value={hex} onChange={(e) => setHex(e.target.value)} placeholder="#RRGGBB" />
            <input type="color" value={hex || "#000000"} onChange={(e) => setHex(e.target.value)} className="h-8 w-10 rounded border border-line" />
          </div>
        </Field>
        <label className="flex items-center gap-2 text-sm text-content"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active</label>
      </div>
    </Modal>
  );
}

// ----------------------------- reorder points -----------------------------
// The threshold at which a model/colour is "running low". A row with no colour is the
// model-wide default; a colour row overrides it for that colour. When sellable stock falls
// to or below this number the low-stock report flags it and (if enabled) a WhatsApp alert
// goes to branch managers. This is purchasing readiness — deliberately separate from the
// assembly targets, which are about workshop throughput.
function ReorderPointsTab() {
  const [table, setTable] = useState<DataTableState>(initialTableState(20));
  const { q, invalidate } = useCrud(
    "setup-reorder-points",
    async () => {
      const rows = await motorcyclesApi.listReorderPoints();
      return { items: rows, total: rows.length };
    },
  );
  const [modal, setModal] = useState<{ item?: ReorderPoint } | null>(null);
  const [removing, setRemoving] = useState<ReorderPoint | null>(null);

  const del = useMutation({
    mutationFn: (id: string) => motorcyclesApi.deleteReorderPoint(id),
    onSuccess: () => { setRemoving(null); void invalidate(); },
  });

  const columns: Column<ReorderPoint>[] = [
    { key: "model", header: "Model", accessor: (r) => r.model_name ?? "—", className: "font-medium text-content" },
    {
      key: "colour", header: "Colour", accessor: (r) => r.colour_name ?? "",
      render: (r) => r.colour_name
        ? r.colour_name
        : <span className="rounded-full bg-surface-muted px-2 py-0.5 text-xs text-muted">All colours (default)</span>,
    },
    { key: "reorder_point", header: "Reorder at", align: "right", accessor: (r) => r.reorder_point,
      render: (r) => <span className="font-medium text-content">{r.reorder_point}</span> },
    { key: "actions", header: "", align: "right", render: (r) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" onClick={() => setModal({ item: r })}>Edit</Button>
        <Button variant="ghost" onClick={() => setRemoving(r)}>Remove</Button>
      </div>
    ) },
  ];
  const items = (q.data?.items ?? []) as ReorderPoint[];

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Set the sellable-stock level at which each model (or a specific colour) is flagged as running low.
        </p>
        <Button onClick={() => setModal({})}>New reorder point</Button>
      </div>
      <DataTable<ReorderPoint> columns={columns} rows={items} total={q.data?.total ?? 0} rowId={(r) => r.id}
        state={table} onStateChange={setTable} loading={q.isLoading} searchable={false}
        storageKey="moto-reorder-points" exportName="motorcycle-reorder-points"
        emptyTitle="No reorder points yet"
        emptyHint="Add one to start monitoring a model or colour for low stock." />
      {modal && <ReorderPointModal item={modal.item} onClose={() => setModal(null)}
        onDone={() => { setModal(null); void invalidate(); }} />}
      {removing && (
        <Modal title="Remove reorder point" size="sm" onClose={() => setRemoving(null)} footer={
          <><Button variant="secondary" onClick={() => setRemoving(null)}>Cancel</Button>
          <Button variant="ghost" className="text-red-600 hover:bg-red-50" disabled={del.isPending}
            onClick={() => del.mutate(removing.id)}>
            {del.isPending ? "Removing…" : "Remove"}</Button></>
        }>
          <p className="text-sm text-content">
            Stop monitoring <span className="font-medium">{removing.model_name}
            {removing.colour_name ? ` (${removing.colour_name})` : " — all colours"}</span> for low stock?
            No stock or history is affected.
          </p>
        </Modal>
      )}
    </>
  );
}

function ReorderPointModal({ item, onClose, onDone }: { item?: ReorderPoint; onClose: () => void; onDone: () => void }) {
  const models = useMotoModels();
  const colours = useMotoColours();
  const [modelId, setModelId] = useState(item?.model_id ?? "");
  const [colourId, setColourId] = useState(item?.colour_id ?? "");
  const [point, setPoint] = useState(item?.reorder_point?.toString() ?? "");
  const [err, setErr] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: () => motorcyclesApi.setReorderPoint({
      model_id: modelId, colour_id: colourId || null, reorder_point: Number(point),
    }),
    onSuccess: onDone,
    // set is an UPSERT keyed on (model, colour), so editing and re-adding the same pair both
    // land on the same row — no duplicate-key error to surface here.
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the reorder point."),
  });
  const pointNum = Number(point);
  const canSave = modelId && point !== "" && Number.isInteger(pointNum) && pointNum >= 0;

  return (
    <Modal title={item ? "Edit reorder point" : "New reorder point"} size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!canSave || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Save"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <Field label="Model *">
          {/* Locked when editing: the (model, colour) pair identifies the row. Change it and
              you'd silently upsert a different one, leaving the original untouched. */}
          <select className={INPUT} value={modelId} disabled={!!item}
            onChange={(e) => setModelId(e.target.value)}>
            <option value="">Select a model…</option>
            {(models.data?.items ?? []).map((mm) => <option key={mm.id} value={mm.id}>{mm.name}</option>)}
          </select>
        </Field>
        <Field label="Colour">
          <select className={INPUT} value={colourId} disabled={!!item}
            onChange={(e) => setColourId(e.target.value)}>
            <option value="">All colours (model-wide default)</option>
            {(colours.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <span className="mt-1 block text-xs text-muted">
            Leave as “All colours” for a default that applies to every colour without its own threshold.
          </span>
        </Field>
        <Field label="Reorder point *">
          <input type="number" min={0} step={1} className={INPUT} value={point}
            onChange={(e) => setPoint(e.target.value)} autoFocus
            placeholder="e.g. 5" />
          <span className="mt-1 block text-xs text-muted">
            Flag as low when sellable stock is at or below this number.
          </span>
        </Field>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-content-muted">{label}</span>
      {children}
    </label>
  );
}
