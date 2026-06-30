// Motorcycle (serialized-unit) registry — list page assembled from the shared DataTable
// + ListPage scaffold. Server-driven (status/branch/sold/search), branch-aware via the
// active-branch context, with a create modal. Rows link to the unit detail page.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bike, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useBranchContext } from "@/lib/branchContext";
import { formatNumber } from "@/lib/format";
import { motorcyclesApi, type MotorcycleUnit, type UnitStatus } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";

const PAGE_SIZE = 20;
const STATUSES: UnitStatus[] = [
  "received", "assembly_required", "in_assembly", "assembled", "inspected",
  "reserved", "sold", "delivered", "registered", "warranty_active", "cancelled",
];

const INPUT =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function MotorcyclesPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canManage = hasPermission("motorcycle.manage");
  const { branchId } = useBranchContext();
  const [status, setStatus] = useState("");
  const [sold, setSold] = useState("");
  const [table, setTable] = useState<DataTableState>(initialTableState(PAGE_SIZE));
  const [creating, setCreating] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["motorcycles", branchId, status, sold, table.search, table.page],
    queryFn: () =>
      motorcyclesApi.list({
        branch_id: branchId ?? undefined,
        status: status || undefined,
        sold: sold === "" ? undefined : sold === "sold",
        search: table.search || undefined,
        page: table.page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (p) => p,
  });

  const columns: Column<MotorcycleUnit>[] = [
    { key: "chassis", header: "Chassis", accessor: (u) => u.chassis_number, className: "font-mono text-[13px] text-content" },
    { key: "model", header: "Model", accessor: (u) => u.model ?? "—" },
    { key: "colour", header: "Colour", accessor: (u) => u.colour ?? "—", defaultHidden: true },
    { key: "branch", header: "Branch", accessor: (u) => u.branch_name ?? "—" },
    { key: "customer", header: "Customer", accessor: (u) => u.customer_name ?? "—" },
    { key: "status", header: "Status", accessor: (u) => u.status, render: (u) => <StatusBadge status={u.status} /> },
    { key: "price", header: "Price", align: "right", accessor: (u) => formatNumber(u.selling_price, { minimumFractionDigits: 2 }), className: "font-mono text-[13px]" },
  ];

  return (
    <>
      <ListPage<MotorcycleUnit>
        title="Motorcycles"
        description="Serialized-unit registry — each chassis tracked through its lifecycle."
        icon={<Bike className="h-5 w-5" />}
        actions={
          canManage ? (
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> New unit
            </Button>
          ) : undefined
        }
        table={{
          columns,
          rows: data?.items ?? [],
          total: data?.total ?? 0,
          rowId: (u) => u.id,
          state: table,
          onStateChange: setTable,
          loading: isFetching && !data,
          searchPlaceholder: "Search chassis, engine or registration",
          storageKey: "motorcycles-table",
          exportName: "motorcycles",
          onRowClick: (u) => navigate(`/motorcycles/${u.id}`),
          emptyTitle: "No units found",
          emptyHint: "Register a unit, or adjust the filters.",
          filters: (
            <>
              <select value={status} onChange={(e) => { setStatus(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}
                className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
                <option value="">All statuses</option>
                {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
              </select>
              <select value={sold} onChange={(e) => { setSold(e.target.value); setTable((t) => ({ ...t, page: 1 })); }}
                className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
                <option value="">Sold & unsold</option>
                <option value="unsold">Unsold</option>
                <option value="sold">Sold</option>
              </select>
            </>
          ),
        }}
      />
      {creating && (
        <CreateUnitModal
          onClose={() => setCreating(false)}
          onCreated={(u) => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["motorcycles"] });
            navigate(`/motorcycles/${u.id}`);
          }}
        />
      )}
    </>
  );
}

function CreateUnitModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (u: MotorcycleUnit) => void;
}) {
  const { list: branches } = useBranches();
  const [form, setForm] = useState({
    chassis_number: "", engine_number: "", model: "", colour: "", year: "",
    branch_id: "", selling_price: "", assembly_required: false,
  });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof form, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  const create = useMutation({
    mutationFn: () =>
      motorcyclesApi.create({
        chassis_number: form.chassis_number.trim(),
        engine_number: form.engine_number || null,
        model: form.model || null,
        colour: form.colour || null,
        year: form.year ? Number(form.year) : null,
        branch_id: form.branch_id || null,
        selling_price: form.selling_price ? Number(form.selling_price) : 0,
        assembly_required: form.assembly_required,
      }),
    onSuccess: onCreated,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create unit."),
  });

  return (
    <Modal
      title="Register a unit"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button disabled={!form.chassis_number.trim() || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>
            {create.isPending ? "Saving…" : "Create"}
          </Button>
        </>
      }
    >
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Chassis number *">
          <input className={INPUT} value={form.chassis_number} onChange={(e) => set("chassis_number", e.target.value)} />
        </Field>
        <Field label="Engine number">
          <input className={INPUT} value={form.engine_number} onChange={(e) => set("engine_number", e.target.value)} />
        </Field>
        <Field label="Model">
          <input className={INPUT} value={form.model} onChange={(e) => set("model", e.target.value)} />
        </Field>
        <Field label="Colour">
          <input className={INPUT} value={form.colour} onChange={(e) => set("colour", e.target.value)} />
        </Field>
        <Field label="Year">
          <input className={INPUT} type="number" value={form.year} onChange={(e) => set("year", e.target.value)} />
        </Field>
        <Field label="Selling price">
          <input className={INPUT} type="number" value={form.selling_price} onChange={(e) => set("selling_price", e.target.value)} />
        </Field>
        <Field label="Branch">
          <select className={INPUT} value={form.branch_id} onChange={(e) => set("branch_id", e.target.value)}>
            <option value="">—</option>
            {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </Field>
        <label className="mt-6 flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={form.assembly_required} onChange={(e) => set("assembly_required", e.target.checked)} />
          Requires assembly
        </label>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}
