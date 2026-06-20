import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { SupplierFormModal } from "@/components/SupplierFormModal";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { catalogApi } from "@/lib/catalog";
import type { Supplier } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const PAGE_SIZE = 20;

export default function SuppliersPage() {
  const { hasPermission } = useAuth();
  const canCreate = hasPermission("supplier.create");
  const canEdit = hasPermission("supplier.update");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ mode: "create" | "edit"; item?: Supplier } | null>(null);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["suppliers", search, page],
    queryFn: () => catalogApi.suppliers({ search: search || undefined, page, page_size: PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Suppliers"
        description="Vendors you buy from, with contact and terms."
        actions={
          canCreate ? (
            <Button onClick={() => setModal({ mode: "create" })}>
              <Plus className="h-4 w-4" /> New supplier
            </Button>
          ) : undefined
        }
      />

      <div className="mb-4 flex items-center gap-3">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search name, contact or email"
          className={`${INPUT} w-72`}
        />
        {isFetching && <Spinner />}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading suppliers…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load suppliers. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No suppliers found</p>
          <p className="mt-1 text-sm text-slate-400">Try a different search.</p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Contact</th>
                  <th className="px-4 py-2.5 font-medium">Country</th>
                  <th className="px-4 py-2.5 font-medium">Currency</th>
                  <th className="px-4 py-2.5 font-medium">Terms</th>
                  <th className="px-4 py-2.5 text-right font-medium">Lead time</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  {canEdit && <th className="px-4 py-2.5 text-right font-medium">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-800">{s.name}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {s.contact_person ?? "—"}
                      {s.email && <div className="text-xs text-slate-400">{s.email}</div>}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{s.country ?? "—"}</td>
                    <td className="px-4 py-3 font-mono text-[13px] text-slate-600">{s.currency}</td>
                    <td className="px-4 py-3 text-slate-600">{s.payment_terms ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                      {s.default_lead_time_days} d
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={s.status} />
                    </td>
                    {canEdit && (
                      <td className="px-4 py-3 text-right">
                        <Button variant="ghost" onClick={() => setModal({ mode: "edit", item: s })}>
                          Edit
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Pagination
        page={data?.page ?? 1}
        totalPages={data?.total_pages ?? 0}
        total={data?.total ?? 0}
        onChange={setPage}
      />

      {modal && (
        <SupplierFormModal mode={modal.mode} initial={modal.item} onClose={() => setModal(null)} />
      )}
    </div>
  );
}
