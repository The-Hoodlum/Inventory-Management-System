import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AdjustStockModal } from "@/components/AdjustStockModal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { TransferStockModal } from "@/components/TransferStockModal";
import { Button, Card, Spinner } from "@/components/ui";
import { catalogApi } from "@/lib/catalog";
import { formatQty, shortId } from "@/lib/format";
import { useProducts, useWarehouses } from "@/lib/refdata";
import type { InventoryRow } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const PAGE_SIZE = 50;

export default function InventoryPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canAdjust = hasPermission("inventory.adjust");
  const canTransfer = hasPermission("inventory.transfer");
  const canImport = hasPermission("data.import");
  const [warehouseId, setWarehouseId] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [adjustRow, setAdjustRow] = useState<InventoryRow | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);

  const { map: productMap } = useProducts();
  const { list: warehouses, map: warehouseMap } = useWarehouses();

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["inventory", warehouseId, search, page],
    queryFn: () =>
      catalogApi.inventory({
        warehouse_id: warehouseId || undefined,
        search: search.trim() || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Inventory"
        description="On-hand, reserved, damaged and available stock by location."
        actions={
          <div className="flex items-center gap-2">
            {canImport && (
              <Button variant="secondary" onClick={() => navigate("/import/inventory")}>
                <Upload className="h-4 w-4" /> Import Inventory
              </Button>
            )}
            {canTransfer && (
              <Button variant="secondary" onClick={() => setTransferOpen(true)}>
                <ArrowRightLeft className="h-4 w-4" /> Transfer stock
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
          placeholder="Search parts by name, SKU or location…"
          className={`${INPUT} w-72`}
        />
        <label className="text-sm text-slate-500" htmlFor="wh">
          Warehouse
        </label>
        <select
          id="wh"
          value={warehouseId}
          onChange={(e) => {
            setWarehouseId(e.target.value);
            setPage(1);
          }}
          className={`${INPUT} w-60`}
        >
          <option value="">All warehouses</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        {isFetching && <Spinner />}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading inventory…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load inventory. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No stock records</p>
          <p className="mt-1 text-sm text-slate-400">
            Receive stock against a purchase order to see it here.
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Product</th>
                  <th className="px-4 py-2.5 font-medium">Location</th>
                  <th className="px-4 py-2.5 font-medium">Warehouse</th>
                  <th className="px-4 py-2.5 text-right font-medium">On hand</th>
                  <th className="px-4 py-2.5 text-right font-medium">Reserved</th>
                  <th className="px-4 py-2.5 text-right font-medium">Damaged</th>
                  <th className="px-4 py-2.5 text-right font-medium">Available</th>
                  {canAdjust && <th className="px-4 py-2.5 text-right font-medium">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((row) => {
                  const product = productMap.get(row.product_id);
                  const available = Number(row.qty_available);
                  return (
                    <tr key={`${row.product_id}:${row.warehouse_id}`} className="hover:bg-slate-50">
                      <td className="px-4 py-3 text-slate-700">
                        <div className="font-medium">{product?.name ?? shortId(row.product_id)}</div>
                        {product?.sku && (
                          <div className="font-mono text-xs text-slate-400">{product.sku}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {product?.location ? (
                          <span className="inline-flex rounded-pill bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600">
                            {product.location}
                          </span>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {warehouseMap.get(row.warehouse_id)?.name ?? shortId(row.warehouse_id)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-700">
                        {formatQty(row.qty_on_hand)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                        {formatQty(row.qty_reserved)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                        {formatQty(row.qty_damaged)}
                      </td>
                      <td
                        className={`px-4 py-3 text-right font-mono text-[13px] font-semibold ${
                          available <= 0 ? "text-red-600" : "text-slate-900"
                        }`}
                      >
                        {formatQty(row.qty_available)}
                      </td>
                      {canAdjust && (
                        <td className="px-4 py-3 text-right">
                          <Button variant="ghost" onClick={() => setAdjustRow(row)}>
                            Adjust
                          </Button>
                        </td>
                      )}
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

      {adjustRow && (
        <AdjustStockModal
          productId={adjustRow.product_id}
          warehouseId={adjustRow.warehouse_id}
          productLabel={productMap.get(adjustRow.product_id)?.name ?? shortId(adjustRow.product_id)}
          warehouseLabel={
            warehouseMap.get(adjustRow.warehouse_id)?.name ?? shortId(adjustRow.warehouse_id)
          }
          currentOnHand={adjustRow.qty_on_hand}
          onClose={() => setAdjustRow(null)}
        />
      )}
      {transferOpen && <TransferStockModal onClose={() => setTransferOpen(false)} />}
    </div>
  );
}
