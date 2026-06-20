import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { WarehouseFormModal } from "@/components/WarehouseFormModal";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { catalogApi } from "@/lib/catalog";
import type { Warehouse } from "@/types/api";

const PAGE_SIZE = 50;

export default function WarehousesPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("warehouse.manage");
  const [activeOnly, setActiveOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ mode: "create" | "edit"; item?: Warehouse } | null>(null);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["warehouses-page", activeOnly, page],
    queryFn: () => catalogApi.warehouses({ active_only: activeOnly, page, page_size: PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Warehouses"
        description="Stocking locations across your network."
        actions={
          canManage ? (
            <Button onClick={() => setModal({ mode: "create" })}>
              <Plus className="h-4 w-4" /> New warehouse
            </Button>
          ) : undefined
        }
      />

      <label className="mb-4 flex w-fit items-center gap-2 text-sm text-slate-600">
        <input
          type="checkbox"
          checked={activeOnly}
          onChange={(e) => {
            setActiveOnly(e.target.checked);
            setPage(1);
          }}
          className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
        />
        Active only
        {isFetching && <Spinner />}
      </label>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading warehouses…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load warehouses. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No warehouses yet</p>
          <p className="mt-1 text-sm text-slate-400">Locations you stock will appear here.</p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Code</th>
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Address</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                {canManage && <th className="px-4 py-2.5 text-right font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((w) => (
                <tr key={w.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-[13px] text-slate-800">{w.code}</td>
                  <td className="px-4 py-3 font-medium text-slate-800">{w.name}</td>
                  <td className="px-4 py-3 text-slate-600">{w.address ?? "—"}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={w.is_active ? "active" : "inactive"} />
                  </td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      <Button variant="ghost" onClick={() => setModal({ mode: "edit", item: w })}>
                        Edit
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Pagination
        page={data?.page ?? 1}
        totalPages={data?.total_pages ?? 0}
        total={data?.total ?? 0}
        onChange={setPage}
      />

      {modal && (
        <WarehouseFormModal mode={modal.mode} initial={modal.item} onClose={() => setModal(null)} />
      )}
    </div>
  );
}
