// Branches admin — create / edit / list the tenant's sites. Assembled from the shared
// ListPage + DataTable + Modal. Branches are matched BY NAME by the motorcycle import
// and stock transfers, so this is where you set those names. View: inventory.read;
// manage: warehouse.manage.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type Branch, type BranchInput, branchesApi } from "@/lib/branches";
import { formatDate } from "@/lib/format";

const PAGE_SIZE = 50;
const INPUT =
  "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function BranchesPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("warehouse.manage");
  const [table, setTable] = useState<DataTableState>(initialTableState(PAGE_SIZE));
  const [modal, setModal] = useState<{ item?: Branch } | null>(null);

  const { data, isFetching } = useQuery({
    queryKey: ["branches-admin", table.page],
    queryFn: () => branchesApi.list({ page: table.page, page_size: PAGE_SIZE }),
    placeholderData: (p) => p,
  });

  const columns: Column<Branch>[] = [
    { key: "code", header: "Code", accessor: (b) => b.code, className: "font-mono text-[13px] text-content" },
    { key: "name", header: "Name", accessor: (b) => b.name, render: (b) => <b>{b.name}</b> },
    { key: "status", header: "Status", accessor: (b) => (b.is_active ? "active" : "inactive"), render: (b) => <StatusBadge status={b.is_active ? "active" : "inactive"} /> },
    { key: "created", header: "Created", accessor: (b) => formatDate(b.created_at), defaultHidden: true },
  ];
  if (canManage) {
    columns.push({
      key: "actions", header: "", align: "right",
      render: (b) => <Button variant="ghost" onClick={() => setModal({ item: b })}>Edit</Button>,
    });
  }

  return (
    <>
      <ListPage<Branch>
        title="Branches"
        description="Your sites. Warehouses belong to a branch; the motorcycle import matches branches by name."
        icon={<Building2 className="h-5 w-5" />}
        actions={canManage ? (
          <Button onClick={() => setModal({})}><Plus className="h-4 w-4" /> New branch</Button>
        ) : undefined}
        table={{
          columns,
          rows: data?.items ?? [],
          total: data?.total ?? 0,
          rowId: (b) => b.id,
          state: table,
          onStateChange: setTable,
          loading: isFetching && !data,
          searchable: false,
          storageKey: "branches-table",
          exportName: "branches",
          emptyTitle: "No branches yet",
          emptyHint: canManage ? "Create your first branch to start." : undefined,
        }}
      />
      {modal && <BranchModal item={modal.item} onClose={() => setModal(null)} />}
    </>
  );
}

function BranchModal({ item, onClose }: { item?: Branch; onClose: () => void }) {
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("warehouse.manage");
  const [name, setName] = useState(item?.name ?? "");
  const [code, setCode] = useState(item?.code ?? "");
  const [active, setActive] = useState(item?.is_active ?? true);
  const [err, setErr] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const body: BranchInput = { name: name.trim(), code: (code.trim() || name.trim()), is_active: active };
      return item ? branchesApi.update(item.id, body) : branchesApi.create(body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["branches-admin"] });
      void qc.invalidateQueries({ queryKey: ["ref", "branches"] }); // refresh the branch switcher + pickers
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the branch."),
  });

  const del = useMutation({
    mutationFn: () => branchesApi.delete(item!.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["branches-admin"] });
      void qc.invalidateQueries({ queryKey: ["ref", "branches"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not delete the branch."),
  });
  const busy = save.isPending || del.isPending;
  const onDelete = () => {
    if (window.confirm(`Delete branch "${item?.name}"? This can't be undone.`)) {
      setErr(null);
      del.mutate();
    }
  };

  return (
    <Modal title={item ? "Edit branch" : "New branch"} size="md" onClose={onClose} footer={
      <div className="flex w-full items-center justify-between">
        <div>
          {item && canManage && (
            <Button variant="ghost" className="text-red-600 hover:bg-red-50" disabled={busy} onClick={onDelete}>
              Delete
            </Button>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button disabled={!name.trim() || busy} onClick={() => { setErr(null); save.mutate(); }}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          A branch is a top-level site (e.g. Lusaka, Ndola). Locations/warehouses live inside a
          branch — add those under Warehouses, not here.
        </p>
        <Field label="Name *">
          <input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} autoFocus
            placeholder="e.g. Lusaka" />
        </Field>
        <Field label="Code">
          <input className={INPUT} value={code} onChange={(e) => setCode(e.target.value)}
            placeholder="Short code (defaults to the name)" />
        </Field>
        <label className="flex items-center gap-2 text-sm text-content">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active
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
