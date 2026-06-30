import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { NewOrderRequestModal } from "@/components/NewOrderRequestModal";
import { NewTransferModal } from "@/components/NewTransferModal";
import { OrderRequestDetailModal } from "@/components/OrderRequestDetailModal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard, StatusBadge } from "@/components/ui";
import { formatDate, titleCase } from "@/lib/format";
import { orderRequestsApi, PURPOSES } from "@/lib/orderRequests";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const STATUSES = [
  "draft", "pending", "approved", "partially_approved", "rejected",
  "partially_issued", "issued", "in_transit", "partially_received", "received",
  "completed", "cancelled",
];

export default function OrderRequestsPage() {
  const { hasPermission } = useAuth();
  const canCreate = hasPermission("order_request.create");
  const canApprove = hasPermission("order_request.approve");
  const canIssue = hasPermission("order_request.issue");
  const canReceive = hasPermission("order_request.receive");
  const canComplete = hasPermission("order_request.complete");

  const [statusFilter, setStatusFilter] = useState("");
  const [purposeFilter, setPurposeFilter] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showTransfer, setShowTransfer] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const dash = useQuery({ queryKey: ["order-requests", "dashboard"], queryFn: orderRequestsApi.dashboard });
  const list = useQuery({
    queryKey: ["order-requests", "list", statusFilter, purposeFilter],
    queryFn: () =>
      orderRequestsApi.list({ status: statusFilter || undefined, purpose: purposeFilter || undefined }),
    placeholderData: (prev) => prev,
  });

  return (
    <div>
      <PageHeader
        title="Order Requests"
        description="Branch requisitions: request stock from the depot, then track approval and issue."
        actions={
          canCreate ? (
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setShowNew(true)}>
                <Plus className="h-4 w-4" /> New request
              </Button>
              <Button onClick={() => setShowTransfer(true)}>
                <Plus className="h-4 w-4" /> New transfer
              </Button>
            </div>
          ) : undefined
        }
      />

      {/* Dashboard widgets */}
      {dash.data && (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
          {dash.data.scope === "admin" ? (
            <>
              <StatCard label="Pending" value={dash.data.pending} tone="warning" />
              <StatCard label="Approved" value={dash.data.approved} tone="positive" />
              <StatCard label="Issued today" value={dash.data.issued_today} />
              <StatCard label="Completed" value={dash.data.completed} tone="positive" />
              <StatCard label="Rejected" value={dash.data.rejected} tone="danger" />
            </>
          ) : (
            <>
              <StatCard label="My pending" value={dash.data.my_pending} tone="warning" />
              <StatCard label="My approved" value={dash.data.my_approved} tone="positive" />
              <StatCard label="My rejected" value={dash.data.my_rejected} tone="danger" />
              <StatCard label="My completed" value={dash.data.my_completed} tone="positive" />
              <StatCard label="Recently issued" value={dash.data.my_recent_issued.length} />
            </>
          )}
        </div>
      )}

      {dash.data?.scope === "admin" && dash.data.most_requested_items.length > 0 && (
        <Card className="mb-5 p-4">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            Most requested items
          </div>
          <div className="flex flex-wrap gap-2">
            {dash.data.most_requested_items.slice(0, 6).map((it) => (
              <span key={it.sku} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">
                {it.name} · <span className="font-mono">{it.total_requested}</span>
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={INPUT}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{titleCase(s)}</option>
          ))}
        </select>
        <select value={purposeFilter} onChange={(e) => setPurposeFilter(e.target.value)} className={INPUT}>
          <option value="">All purposes</option>
          {PURPOSES.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
        {list.isFetching && <Spinner />}
      </div>

      {list.isLoading ? (
        <div className="flex h-48 items-center justify-center"><Spinner label="Loading requests…" /></div>
      ) : list.isError ? (
        <Card className="p-6 text-sm text-red-700">Couldn’t load order requests.</Card>
      ) : !list.data || list.data.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm font-medium text-slate-700">No order requests</p>
          <p className="mt-1 text-sm text-slate-400">
            {canCreate ? "Create one with “New request”." : "Requests you raise will appear here."}
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Request #</th>
                  <th className="px-4 py-2.5 font-medium">Branch</th>
                  {canApprove && <th className="px-4 py-2.5 font-medium">Requested by</th>}
                  <th className="px-4 py-2.5 font-medium">Purpose</th>
                  <th className="px-4 py-2.5 text-right font-medium">Items</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setDetailId(r.id)}
                    className="cursor-pointer hover:bg-slate-50"
                  >
                    <td className="px-4 py-3 font-mono text-[13px] font-medium text-slate-800">{r.request_number}</td>
                    <td className="px-4 py-3 text-slate-600">{r.branch_name ?? "—"}</td>
                    {canApprove && <td className="px-4 py-3 text-slate-600">{r.requester_name ?? "—"}</td>}
                    <td className="px-4 py-3 text-slate-600">{titleCase(r.purpose)}</td>
                    <td className="px-4 py-3 text-right font-mono text-slate-600">{r.lines.length}</td>
                    <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                    <td className="px-4 py-3 text-slate-500">{formatDate(r.requested_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showNew && <NewOrderRequestModal onClose={() => setShowNew(false)} />}
      {showTransfer && <NewTransferModal onClose={() => setShowTransfer(false)} />}
      {detailId && (
        <OrderRequestDetailModal
          requestId={detailId}
          canApprove={canApprove}
          canIssue={canIssue}
          canReceive={canReceive}
          canComplete={canComplete}
          onClose={() => setDetailId(null)}
        />
      )}
    </div>
  );
}
