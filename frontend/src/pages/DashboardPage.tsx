import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, PackageCheck } from "lucide-react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Card, Spinner, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { useBranchContext } from "@/lib/branchContext";
import { formatDate, formatMoney, formatNumber, formatQty, titleCase } from "@/lib/format";
import { useMotoMetrics } from "@/lib/motorcycles";
import { useInventoryReport } from "@/lib/reports";
import type { DashboardMetrics } from "@/types/api";

const STATUS_ORDER = [
  "draft",
  "pending_approval",
  "approved",
  "sent",
  "partially_received",
  "received",
  "cancelled",
  "rejected",
];

const STATUS_COLOR: Record<string, string> = {
  draft: "#94a3b8",
  pending_approval: "#f59e0b",
  approved: "#6366f1",
  sent: "#4f46e5",
  partially_received: "#06b6d4",
  received: "#10b981",
  cancelled: "#cbd5e1",
  rejected: "#ef4444",
};

export default function DashboardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard", "metrics"],
    queryFn: () => api.get<DashboardMetrics>("/dashboard/metrics"),
  });

  const { hasPermission } = useAuth();
  const canInv = hasPermission("inventory.read");
  const canMoto = hasPermission("motorcycle.read");
  const report = useInventoryReport();
  const { branchId } = useBranchContext();
  const moto = useMotoMetrics(branchId, canMoto);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner label="Loading metrics…" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <Card className="p-6 text-sm text-red-700">
        Couldn’t load dashboard metrics. {(error as Error | null)?.message ?? ""}
      </Card>
    );
  }

  const chartData = STATUS_ORDER.map((s) => ({
    status: s,
    label: titleCase(s),
    count: data.purchase_orders.by_status[s] ?? 0,
  })).filter((d) => d.count > 0);

  const lowStock = data.inventory.low_stock_count;
  const invReady = canInv && !report.isLoading && !report.isError;
  const score = report.healthScore;
  const scoreTone: "positive" | "warning" | "danger" =
    score >= 80 ? "positive" : score >= 50 ? "warning" : "danger";

  return (
    <div>
      <PageHeader title="Dashboard" description={`Updated ${formatDate(data.generated_at)}`} />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        <StatCard
          label="Open POs"
          value={formatNumber(data.purchase_orders.open_count)}
          hint="Approved, sent or receiving"
        />
        <StatCard label="Open PO value" value={formatMoney(data.purchase_orders.open_value)} />
        <StatCard
          label="Low stock items"
          value={formatNumber(lowStock)}
          tone={lowStock > 0 ? "warning" : "positive"}
          hint="At or below reorder point"
        />
        <StatCard label="Receipts (30d)" value={formatNumber(data.activity.receipts_last_30d)} />
        <StatCard
          label="On hand"
          value={formatQty(data.inventory.total_on_hand)}
          hint="Units across warehouses"
        />
        <StatCard label="Available" value={formatQty(data.inventory.total_available)} />
        <StatCard label="Reserved" value={formatQty(data.inventory.total_reserved)} />
        <StatCard
          label="Catalog"
          value={`${data.catalog.products} / ${data.catalog.suppliers}`}
          hint={`products / suppliers · ${data.catalog.warehouses} warehouses`}
        />
      </div>

      {invReady && (
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          <StatCard
            label="Inventory value (cost)"
            value={formatMoney(report.totalCostValue)}
            hint={`Retail ${formatMoney(report.totalRetailValue)}`}
          />
          <StatCard
            label="Inventory health"
            value={`${score} / 100`}
            tone={scoreTone}
            hint="100 − %out − 0.4 × %low"
          />
          <StatCard
            label="Out of stock"
            value={formatNumber(report.statusCounts.out)}
            tone={report.statusCounts.out > 0 ? "danger" : "positive"}
            hint="Lines at zero available"
          />
          <StatCard label="Stock lines" value={formatNumber(report.totalLines)} hint="Product · warehouse" />
        </div>
      )}

      {canMoto && moto.data && moto.data.total > 0 && (
        <div className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-slate-800">Motorcycles</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Units" value={formatNumber(moto.data.total)} hint="Serialized units on record" />
            <StatCard label="In stock" value={formatNumber(moto.data.in_stock)} tone="positive" hint="On hand, not yet sold" />
            <StatCard label="Reserved" value={formatNumber(moto.data.reserved)} tone="warning" hint="Held for a customer" />
            <StatCard label="Sold" value={formatNumber(moto.data.sold)} hint="Delivered / registered incl." />
          </div>
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold text-slate-800">Purchase orders by status</h2>
          {chartData.length === 0 ? (
            <p className="mt-6 text-sm text-slate-400">No purchase orders yet.</p>
          ) : (
            <div className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 11 }}
                    interval={0}
                    angle={-15}
                    textAnchor="end"
                    height={50}
                    stroke="#94a3b8"
                  />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="#94a3b8" />
                  <Tooltip cursor={{ fill: "#f1f5f9" }} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {chartData.map((d) => (
                      <Cell key={d.status} fill={STATUS_COLOR[d.status] ?? "#6366f1"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="text-sm font-semibold text-slate-800">Attention</h2>
          <div className="mt-4 space-y-3">
            <div className="flex items-start gap-3">
              <span
                className={
                  "mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg " +
                  (lowStock > 0
                    ? "bg-amber-100 text-amber-600"
                    : "bg-emerald-100 text-emerald-600")
                }
              >
                <AlertTriangle className="h-4 w-4" />
              </span>
              <div>
                <div className="text-sm font-medium text-slate-800">
                  {lowStock} item(s) at or below reorder point
                </div>
                <div className="text-xs text-slate-400">
                  Review reorder recommendations to replenish.
                </div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
                <PackageCheck className="h-4 w-4" />
              </span>
              <div>
                <div className="text-sm font-medium text-slate-800">
                  {data.purchase_orders.open_count} open purchase order(s)
                </div>
                <div className="text-xs text-slate-400">Awaiting delivery or in receiving.</div>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
