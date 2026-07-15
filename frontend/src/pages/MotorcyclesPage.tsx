// Motorcycles — the serialized-unit registry list. Assembled from the shared ListPage +
// DataTable (server-driven: filters by status/branch/model/colour/sold, search by
// chassis/engine/registration, saved views + CSV export come for free).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bike, Plus, Settings2, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AssemblyBadge } from "@/components/AssemblyBadge";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  type MotoUnit,
  motorcyclesApi,
  statusLabel,
  UNIT_STATUSES,
  useMotoColours,
  useMotoModels,
} from "@/lib/motorcycles";
import { useBranches, useWarehouses } from "@/lib/refdata";

const PAGE_SIZE = 20;
const SELECT =
  "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function MotorcyclesPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canManage = hasPermission("motorcycle.manage");
  const canConfig = hasPermission("motorcycle.config");
  const canImport = hasPermission("data.import") && canManage;

  const [table, setTable] = useState<DataTableState>(initialTableState(PAGE_SIZE));
  const [status, setStatus] = useState("");
  const [branch, setBranch] = useState("");
  const [model, setModel] = useState("");
  const [colour, setColour] = useState("");
  const [sold, setSold] = useState("");
  const [inspected, setInspected] = useState("");
  const [registered, setRegistered] = useState("");
  const [showNew, setShowNew] = useState(false);

  const { list: branches } = useBranches();
  const models = useMotoModels();
  const colours = useMotoColours();

  const { data, isFetching } = useQuery({
    queryKey: ["moto", "units", table.search, status, branch, model, colour, sold, inspected, registered, table.page],
    queryFn: () =>
      motorcyclesApi.listUnits({
        search: table.search || undefined,
        status: status || undefined,
        branch_id: branch || undefined,
        model_id: model || undefined,
        colour_id: colour || undefined,
        sold: sold === "" ? undefined : sold === "sold",
        inspected: inspected === "" ? undefined : inspected === "yes",
        registered: registered === "" ? undefined : registered === "yes",
        page: table.page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (p) => p,
  });

  const columns: Column<MotoUnit>[] = [
    { key: "chassis", header: "Chassis", accessor: (u) => u.chassis_number, className: "font-mono text-[13px] text-content" },
    { key: "engine", header: "Engine no.", accessor: (u) => u.engine_number ?? "—", className: "font-mono text-[13px]", defaultHidden: true },
    { key: "model", header: "Model", accessor: (u) => u.model_name ?? "—" },
    { key: "variant", header: "Variant", accessor: (u) => u.variant_name ?? "—", defaultHidden: true },
    { key: "colour", header: "Colour", accessor: (u) => u.colour_name ?? "—" },
    { key: "origin", header: "Origin", accessor: (u) => u.country_of_origin ?? "—" },
    { key: "branch", header: "Branch", accessor: (u) => u.branch_name ?? "—" },
    { key: "customer", header: "Customer", accessor: (u) => u.customer_name ?? "—", defaultHidden: true },
    { key: "registration", header: "Reg. no.", accessor: (u) => u.registration_number ?? "—", defaultHidden: true },
    { key: "status", header: "Status", accessor: (u) => u.status, render: (u) => <StatusBadge status={u.status} /> },
    { key: "assembly", header: "Assembly", accessor: (u) => (u.assembly_pending ? "owed" : u.assembled_date ? "assembled" : "not_assembled"), render: (u) => <AssemblyBadge unit={u} />, defaultHidden: true },
  ];

  return (
    <>
      <ListPage<MotoUnit>
        title="Motorcycles"
        description="Serialized-unit registry — every physical unit tracked by chassis through its whole life."
        icon={<Bike className="h-5 w-5" />}
        actions={
          <>
            {canConfig && (
              <Button variant="secondary" onClick={() => navigate("/motorcycles/setup")}>
                <Settings2 className="h-4 w-4" /> Setup
              </Button>
            )}
            {canImport && (
              <Button variant="secondary" onClick={() => navigate("/motorcycles/import")}>
                <Upload className="h-4 w-4" /> Import
              </Button>
            )}
            {canManage && (
              <Button onClick={() => setShowNew(true)}>
                <Plus className="h-4 w-4" /> New unit
              </Button>
            )}
          </>
        }
        table={{
          columns,
          rows: data?.items ?? [],
          total: data?.total ?? 0,
          rowId: (u) => u.id,
          state: table,
          onStateChange: setTable,
          loading: isFetching && !data,
          onRowClick: (u) => navigate(`/motorcycles/${u.id}`),
          searchPlaceholder: "Search chassis, engine or registration",
          storageKey: "motorcycle-units-table",
          exportName: "motorcycles",
          emptyTitle: "No motorcycles found",
          emptyHint: "Add a unit or adjust the filters.",
          filters: (
            <div className="flex flex-wrap items-center gap-2">
              <select className={SELECT} value={status} onChange={(e) => { setStatus(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">All statuses</option>
                {UNIT_STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
              </select>
              <select className={SELECT} value={branch} onChange={(e) => { setBranch(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">All branches</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <select className={SELECT} value={model} onChange={(e) => { setModel(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">All models</option>
                {(models.data?.items ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
              <select className={SELECT} value={colour} onChange={(e) => { setColour(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">All colours</option>
                {(colours.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <select className={SELECT} value={sold} onChange={(e) => { setSold(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">Sold & unsold</option>
                <option value="unsold">Unsold</option>
                <option value="sold">Sold</option>
              </select>
              <select className={SELECT} value={inspected} onChange={(e) => { setInspected(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">Any inspection</option>
                <option value="yes">Inspected</option>
                <option value="no">Not inspected</option>
              </select>
              <select className={SELECT} value={registered} onChange={(e) => { setRegistered(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}>
                <option value="">Any registration</option>
                <option value="yes">Registered</option>
                <option value="no">Not registered</option>
              </select>
            </div>
          ),
        }}
      />
      {showNew && <NewUnitModal onClose={() => setShowNew(false)} onCreated={(id) => navigate(`/motorcycles/${id}`)} />}
    </>
  );
}

const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function NewUnitModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const models = useMotoModels();
  const colours = useMotoColours();
  const { list: branches } = useBranches();
  const { list: warehouses } = useWarehouses();

  const [form, setForm] = useState<Record<string, string | boolean>>({ chassis_number: "", assembly_required: false });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  const create = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        chassis_number: String(form.chassis_number).trim(),
        model_id: form.model_id,
        assembly_required: Boolean(form.assembly_required),
      };
      for (const k of ["engine_number", "variant_id", "colour_id", "branch_id", "warehouse_id", "internal_location", "country_of_origin"]) {
        if (form[k]) body[k] = form[k];
      }
      if (form.year) body.year = Number(form.year);
      if (form.selling_price) body.selling_price = Number(form.selling_price);
      return motorcyclesApi.createUnit(body);
    },
    onSuccess: (u) => { void qc.invalidateQueries({ queryKey: ["moto", "units"] }); onCreated(u.id); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the unit."),
  });

  const canSave = String(form.chassis_number).trim().length > 0 && Boolean(form.model_id);

  return (
    <Modal title="New motorcycle unit" size="lg" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!canSave || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>
          {create.isPending ? "Saving…" : "Create"}
        </Button>
      </>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Chassis number *"><input className={INPUT} value={String(form.chassis_number)} onChange={(e) => set("chassis_number", e.target.value)} autoFocus /></Field>
          <Field label="Engine number"><input className={INPUT} value={String(form.engine_number ?? "")} onChange={(e) => set("engine_number", e.target.value)} /></Field>
          <Field label="Model *">
            <select className={INPUT} value={String(form.model_id ?? "")} onChange={(e) => set("model_id", e.target.value)}>
              <option value="">Select a model…</option>
              {(models.data?.items ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.brand_name ? ` · ${m.brand_name}` : ""}</option>)}
            </select>
          </Field>
          <Field label="Country of origin">
            <input className={INPUT} list="unit-origin-suggestions" placeholder="e.g. India, Congo, Kenya" value={String(form.country_of_origin ?? "")} onChange={(e) => set("country_of_origin", e.target.value)} />
            <datalist id="unit-origin-suggestions"><option value="India" /><option value="Congo" /><option value="Kenya" /></datalist>
          </Field>
          <Field label="Colour">
            <select className={INPUT} value={String(form.colour_id ?? "")} onChange={(e) => set("colour_id", e.target.value)}>
              <option value="">—</option>
              {(colours.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Year"><input type="number" className={INPUT} value={String(form.year ?? "")} onChange={(e) => set("year", e.target.value)} /></Field>
          <Field label="Selling price"><input type="number" min={0} className={INPUT} value={String(form.selling_price ?? "")} onChange={(e) => set("selling_price", e.target.value)} /></Field>
          <Field label="Branch">
            <select className={INPUT} value={String(form.branch_id ?? "")} onChange={(e) => set("branch_id", e.target.value)}>
              <option value="">—</option>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </Field>
          <Field label="Location">
            <select className={INPUT} value={String(form.warehouse_id ?? "")} onChange={(e) => set("warehouse_id", e.target.value)}>
              <option value="">—</option>
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-content">
          <input type="checkbox" checked={Boolean(form.assembly_required)} onChange={(e) => set("assembly_required", e.target.checked)} />
          This unit needs assembly before inspection
        </label>
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
