import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Card, Spinner, StatusBadge } from "@/components/ui";
import { formatQty, shortId, titleCase } from "@/lib/format";
import { inventoryApi } from "@/lib/inventory";
import { useProducts, useWarehouses } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const PAGE_SIZE = 50;

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export default function MovementsPage() {
  const [warehouseId, setWarehouseId] = useState("");
  const [productId, setProductId] = useState("");
  const [page, setPage] = useState(1);

  const { list: products, map: productMap } = useProducts();
  const { list: warehouses, map: warehouseMap } = useWarehouses();

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["movements", warehouseId, productId, page],
    queryFn: () =>
      inventoryApi.movements({
        warehouse_id: warehouseId || undefined,
        product_id: productId || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  const whName = (id: string | null) => (id ? warehouseMap.get(id)?.name ?? shortId(id) : "—");

  return (
    <div>
      <PageHeader
        title="Stock movements"
        description="Every receipt, issue, adjustment and transfer, with who and when."
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={warehouseId}
          onChange={(e) => {
            setWarehouseId(e.target.value);
            setPage(1);
          }}
          className={`${INPUT} w-56`}
        >
          <option value="">All warehouses</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <select
          value={productId}
          onChange={(e) => {
            setProductId(e.target.value);
            setPage(1);
          }}
          className={`${INPUT} w-72`}
        >
          <option value="">All products</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.sku} — {p.name}
            </option>
          ))}
        </select>
        {isFetching && <Spinner />}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading movements…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load movements. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No movements found</p>
          <p className="mt-1 text-sm text-slate-400">
            Receipts, issues, adjustments and transfers will appear here.
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">When</th>
                  <th className="px-4 py-2.5 font-medium">Type</th>
                  <th className="px-4 py-2.5 font-medium">Product</th>
                  <th className="px-4 py-2.5 font-medium">Location</th>
                  <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                  <th className="px-4 py-2.5 font-medium">Reference</th>
                  <th className="px-4 py-2.5 font-medium">User</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((m) => {
                  const product = productMap.get(m.product_id);
                  const isTransfer = !!(m.from_warehouse_id && m.to_warehouse_id);
                  return (
                    <tr key={m.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 whitespace-nowrap text-slate-600">
                        {fmtDateTime(m.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={m.movement_type} />
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        <div className="max-w-[16rem] truncate" title={product?.name ?? m.product_id}>
                          {product?.name ?? shortId(m.product_id)}
                        </div>
                        {product?.sku && (
                          <div className="font-mono text-xs text-slate-400">{product.sku}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {isTransfer
                          ? `${whName(m.from_warehouse_id)} → ${whName(m.to_warehouse_id)}`
                          : whName(m.warehouse_id)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-800">
                        {formatQty(m.quantity)}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {m.reference_type ? titleCase(m.reference_type) : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">
                        {m.user_id ? shortId(m.user_id) : "System"}
                      </td>
                    </tr>
                  );
                })}
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
    </div>
  );
}
