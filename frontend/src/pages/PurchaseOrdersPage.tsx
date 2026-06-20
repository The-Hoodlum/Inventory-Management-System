import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { poApi } from "@/lib/po";
import { formatDate, formatMoney, shortId } from "@/lib/format";
import { useSuppliers, useWarehouses } from "@/lib/refdata";
import type { POStatus } from "@/types/api";

const STATUSES: POStatus[] = [
  "draft",
  "pending_approval",
  "approved",
  "sent",
  "partially_received",
  "received",
  "cancelled",
  "rejected",
];

const PAGE_SIZE = 20;

export default function PurchaseOrdersPage() {
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canCreate = hasPermission("po.create");
  const [status, setStatus] = useState<string>("");
  const [page, setPage] = useState(1);

  const { map: supplierMap } = useSuppliers();
  const { map: warehouseMap } = useWarehouses();

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["purchase-orders", status, page],
    queryFn: () => poApi.list({ status: status || undefined, page, page_size: PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });

  const onFilter = (value: string) => {
    setStatus(value);
    setPage(1);
  };

  const totalPages = data?.total_pages ?? 0;

  return (
    <div>
      <PageHeader
        title="Purchase Orders"
        description="Track every PO from draft through receiving."
        actions={
          canCreate ? (
            <Button onClick={() => navigate("/purchase-orders/new")}>
              <Plus className="h-4 w-4" /> New PO
            </Button>
          ) : undefined
        }
      />

      <div className="mb-4 flex items-center gap-3">
        <label className="text-sm text-slate-500" htmlFor="status">
          Status
        </label>
        <select
          id="status"
          value={status}
          onChange={(e) => onFilter(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        {isFetching && <Spinner />}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading purchase orders…" />
        </div>
      ) : isError ? (
        <Card className="p-6 text-sm text-red-700">
          Couldn’t load purchase orders. {(error as Error | null)?.message ?? ""}
        </Card>
      ) : !data || data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No purchase orders here yet</p>
          <p className="mt-1 text-sm text-slate-400">
            Generate drafts from reorder recommendations, or adjust the status filter.
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">PO Number</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Supplier</th>
                <th className="px-4 py-2.5 font-medium">Warehouse</th>
                <th className="px-4 py-2.5 font-medium">Order date</th>
                <th className="px-4 py-2.5 font-medium">Expected</th>
                <th className="px-4 py-2.5 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((po) => (
                <tr
                  key={po.id}
                  onClick={() => navigate(`/purchase-orders/${po.id}`)}
                  className="cursor-pointer hover:bg-slate-50"
                >
                  <td className="px-4 py-3 font-mono text-[13px] text-slate-800">{po.po_number}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={po.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-700">
                    {supplierMap.get(po.supplier_id)?.name ?? shortId(po.supplier_id)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {warehouseMap.get(po.warehouse_id)?.name ?? shortId(po.warehouse_id)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{formatDate(po.order_date)}</td>
                  <td className="px-4 py-3 text-slate-600">{formatDate(po.expected_date)}</td>
                  <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-800">
                    {formatMoney(po.total, po.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
          <span>
            Page {data?.page} of {totalPages} · {data?.total} total
          </span>
          <div className="flex gap-2">
            <button
              className="rounded-lg border border-slate-300 px-3 py-1.5 disabled:opacity-40"
              disabled={(data?.page ?? 1) <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <button
              className="rounded-lg border border-slate-300 px-3 py-1.5 disabled:opacity-40"
              disabled={(data?.page ?? 1) >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
