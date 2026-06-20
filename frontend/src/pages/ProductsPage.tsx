import { useQuery } from "@tanstack/react-query";
import { Plus, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ProductFormModal } from "@/components/ProductFormModal";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { catalogApi } from "@/lib/catalog";
import { formatNumber } from "@/lib/format";
import { useSuppliers } from "@/lib/refdata";
import type { Product, ProductStatus } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const PAGE_SIZE = 20;
const STATUSES: ProductStatus[] = ["active", "inactive", "discontinued"];

function money(v: string): string {
  return formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function ProductsPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canCreate = hasPermission("product.create");
  const canEdit = hasPermission("product.update");
  const canImport = hasPermission("data.import");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ mode: "create" | "edit"; item?: Product } | null>(null);

  const { map: supplierMap } = useSuppliers();

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["products", search, status, page],
    queryFn: () =>
      catalogApi.products({
        search: search || undefined,
        status: status || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Products"
        description="Your catalog, pricing and reorder settings."
        actions={
          <div className="flex items-center gap-2">
            {canImport && (
              <Button variant="secondary" onClick={() => navigate("/import/inventory")}>
                <Upload className="h-4 w-4" /> Import Inventory
              </Button>
            )}
            {canCreate && (
              <Button onClick={() => setModal({ mode: "create" })}>
                <Plus className="h-4 w-4" /> New product
              </Button>
            )}
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search SKU, name or barcode"
          className={`${INPUT} w-72`}
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className={INPUT}
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {isFetching && <Spinner />}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading products…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load products. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No products found</p>
          <p className="mt-1 text-sm text-slate-400">Try a different search or status.</p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">SKU</th>
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Supplier</th>
                  <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                  <th className="px-4 py-2.5 text-right font-medium">Price</th>
                  <th className="px-4 py-2.5 text-right font-medium">Reorder pt</th>
                  <th className="px-4 py-2.5 text-right font-medium">Lead time</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  {canEdit && <th className="px-4 py-2.5 text-right font-medium">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-[13px] text-slate-800">{p.sku}</td>
                    <td className="px-4 py-3 text-slate-700">
                      <div className="max-w-[20rem] truncate" title={p.name}>
                        {p.name}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {p.primary_supplier_id
                        ? supplierMap.get(p.primary_supplier_id)?.name ?? "—"
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                      {money(p.cost_price)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-800">
                      {money(p.selling_price)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                      {p.reorder_point ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                      {p.lead_time_days} d
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={p.status} />
                    </td>
                    {canEdit && (
                      <td className="px-4 py-3 text-right">
                        <Button variant="ghost" onClick={() => setModal({ mode: "edit", item: p })}>
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
        <ProductFormModal mode={modal.mode} initial={modal.item} onClose={() => setModal(null)} />
      )}
    </div>
  );
}
