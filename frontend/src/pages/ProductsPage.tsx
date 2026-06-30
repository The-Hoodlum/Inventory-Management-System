// Products list — assembled from the shared DataTable + ListPage scaffold (no hand-rolled
// table). Demonstrates the server-driven pattern: the page owns the query and passes the
// current page of rows + total for the DataTable's search/pagination state. Column chooser,
// saved views, and CSV export come for free from DataTable.
import { useQuery } from "@tanstack/react-query";
import { Package, Plus, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { ProductFormModal } from "@/components/ProductFormModal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { catalogApi } from "@/lib/catalog";
import { formatNumber } from "@/lib/format";
import { useSuppliers } from "@/lib/refdata";
import type { Product, ProductStatus } from "@/types/api";

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
  const [status, setStatus] = useState<string>("");
  const [table, setTable] = useState<DataTableState>(initialTableState(PAGE_SIZE));
  const [modal, setModal] = useState<{ mode: "create" | "edit"; item?: Product } | null>(null);

  const { map: supplierMap } = useSuppliers();

  const { data, isFetching } = useQuery({
    queryKey: ["products", table.search, status, table.page],
    queryFn: () =>
      catalogApi.products({
        search: table.search || undefined,
        status: status || undefined,
        page: table.page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  const supplierName = (p: Product) =>
    p.primary_supplier_id ? supplierMap.get(p.primary_supplier_id)?.name ?? "—" : "—";

  const columns: Column<Product>[] = [
    { key: "sku", header: "SKU", accessor: (p) => p.sku, className: "font-mono text-[13px] text-content" },
    {
      key: "name",
      header: "Name",
      accessor: (p) => p.name,
      render: (p) => <span className="block max-w-[20rem] truncate" title={p.name}>{p.name}</span>,
    },
    { key: "supplier", header: "Supplier", accessor: supplierName },
    { key: "cost", header: "Cost", align: "right", accessor: (p) => money(p.cost_price), className: "font-mono text-[13px]" },
    { key: "price", header: "Price", align: "right", accessor: (p) => money(p.selling_price), className: "font-mono text-[13px] text-content" },
    { key: "reorder", header: "Reorder pt", align: "right", accessor: (p) => p.reorder_point ?? "—", defaultHidden: true },
    { key: "lead", header: "Lead time", align: "right", accessor: (p) => `${p.lead_time_days} d`, defaultHidden: true },
    { key: "status", header: "Status", accessor: (p) => p.status, render: (p) => <StatusBadge status={p.status} /> },
  ];
  if (canEdit) {
    columns.push({
      key: "actions",
      header: "",
      align: "right",
      render: (p) => (
        <Button variant="ghost" onClick={() => setModal({ mode: "edit", item: p })}>
          Edit
        </Button>
      ),
    });
  }

  return (
    <>
      <ListPage<Product>
        title="Products"
        description="Your catalog, pricing and reorder settings."
        icon={<Package className="h-5 w-5" />}
        actions={
          <>
            {canImport && (
              <Button variant="secondary" onClick={() => navigate("/import/inventory")}>
                <Upload className="h-4 w-4" /> Import
              </Button>
            )}
            {canCreate && (
              <Button onClick={() => setModal({ mode: "create" })}>
                <Plus className="h-4 w-4" /> New product
              </Button>
            )}
          </>
        }
        table={{
          columns,
          rows: data?.items ?? [],
          total: data?.total ?? 0,
          rowId: (p) => p.id,
          state: table,
          onStateChange: setTable,
          loading: isFetching && !data,
          searchPlaceholder: "Search SKU, name or barcode",
          storageKey: "products-table",
          exportName: "products",
          emptyTitle: "No products found",
          emptyHint: "Try a different search or status.",
          filters: (
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setTable((t) => ({ ...t, page: 1 }));
              }}
              className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          ),
        }}
      />

      {modal && (
        <ProductFormModal mode={modal.mode} initial={modal.item} onClose={() => setModal(null)} />
      )}
    </>
  );
}
