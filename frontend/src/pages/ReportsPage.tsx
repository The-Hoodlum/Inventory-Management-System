import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard } from "@/components/ui";
import { formatDate, formatMoney, formatNumber, formatQty, shortId } from "@/lib/format";
import { useInventoryReport, useMovers } from "@/lib/reports";
import { useInventoryAging, useStockPosition, useSupplierPerformance } from "@/lib/serverReports";
import { useWarehouses } from "@/lib/refdata";

type Tab = "valuation" | "low" | "out" | "position" | "movers" | "suppliers" | "aging";

const TABS: { id: Tab; label: string }[] = [
  { id: "valuation", label: "Valuation" },
  { id: "low", label: "Low stock" },
  { id: "out", label: "Out of stock" },
  { id: "position", label: "Stock position" },
  { id: "movers", label: "Fast / slow movers" },
  { id: "suppliers", label: "Supplier performance" },
  { id: "aging", label: "Aging" },
];

const BUCKET_LABELS = ["0-30", "31-60", "61-90", "90+"];

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
const pctTone = (v: number | null) =>
  v === null ? "text-slate-400" : v >= 0.9 ? "text-emerald-700" : v >= 0.7 ? "text-amber-700" : "text-red-600";

const TH = "px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-slate-500";
const THR = "px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-slate-500";
const TD = "px-4 py-3 text-slate-700";
const TDR = "px-4 py-3 text-right font-mono text-[13px]";

export default function ReportsPage() {
  const { hasPermission } = useAuth();
  const canMovers = hasPermission("reorder.run");

  const report = useInventoryReport();
  const { list: warehouses, map: warehouseMap } = useWarehouses();

  const [tab, setTab] = useState<Tab>("valuation");
  const [warehouseId, setWarehouseId] = useState("");
  const [moversDir, setMoversDir] = useState<"fast" | "slow">("fast");

  const movers = useMovers(tab === "movers" && canMovers);
  const aging = useInventoryAging(warehouseId, tab === "aging");
  const position = useStockPosition("", warehouseId, tab === "position");
  const supplierPerf = useSupplierPerformance(365, tab === "suppliers");

  const rows = useMemo(
    () => (warehouseId ? report.rows.filter((r) => r.warehouseId === warehouseId) : report.rows),
    [report.rows, warehouseId]
  );

  const totals = useMemo(() => {
    const t = { cost: 0, retail: 0, onHand: 0, out: 0, low: 0 };
    for (const r of rows) {
      t.cost += r.costValue;
      t.retail += r.retailValue;
      t.onHand += r.onHand;
      if (r.status === "out") t.out += 1;
      else if (r.status === "low") t.low += 1;
    }
    return t;
  }, [rows]);

  const byWh = useMemo(() => {
    const m = new Map<string, { id: string; lines: number; onHand: number; cost: number; retail: number }>();
    for (const r of rows) {
      const w = m.get(r.warehouseId) ?? {
        id: r.warehouseId,
        lines: 0,
        onHand: 0,
        cost: 0,
        retail: 0,
      };
      w.lines += 1;
      w.onHand += r.onHand;
      w.cost += r.costValue;
      w.retail += r.retailValue;
      m.set(r.warehouseId, w);
    }
    return [...m.values()].sort((a, b) => b.cost - a.cost);
  }, [rows]);

  const valuationRows = useMemo(
    () => [...rows].sort((a, b) => b.costValue - a.costValue).slice(0, 500),
    [rows]
  );
  const lowRows = useMemo(
    () =>
      rows
        .filter((r) => r.status === "low")
        .sort((a, b) => b.reorderPoint - b.available - (a.reorderPoint - a.available)),
    [rows]
  );
  const outRows = useMemo(
    () => rows.filter((r) => r.status === "out").sort((a, b) => a.name.localeCompare(b.name)),
    [rows]
  );
  const moverRows = useMemo(() => {
    const list = [...movers.rows];
    list.sort((a, b) => (moversDir === "fast" ? b.avgMonthly - a.avgMonthly : a.avgMonthly - b.avgMonthly));
    return list.slice(0, 25);
  }, [movers.rows, moversDir]);

  const whName = (id: string) => warehouseMap.get(id)?.name ?? shortId(id);

  const inventoryTab = tab === "valuation" || tab === "low" || tab === "out";

  return (
    <div>
      <PageHeader title="Reports" description="Inventory valuation, stock health and demand movers." />

      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={
              "rounded-t-lg px-4 py-2 text-sm font-medium transition " +
              (tab === t.id
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-700")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {(inventoryTab || tab === "aging" || tab === "position") && warehouses.length > 0 && (
        <div className="mb-4 flex items-center gap-3">
          <label className="text-sm text-slate-500" htmlFor="rwh">
            Warehouse
          </label>
          <select
            id="rwh"
            value={warehouseId}
            onChange={(e) => setWarehouseId(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            <option value="">All warehouses</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Inventory-derived tabs share one fetch */}
      {inventoryTab &&
        (report.isLoading ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner label="Computing report…" />
          </div>
        ) : report.isError ? (
          <Card className="p-6 text-sm text-red-700">
            Couldn’t load inventory data. {report.error?.message ?? ""}
          </Card>
        ) : rows.length === 0 ? (
          <Card className="p-10 text-center text-sm text-slate-400">No stock records to report on.</Card>
        ) : tab === "valuation" ? (
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label="Inventory value (cost)" value={formatMoney(totals.cost)} />
              <StatCard label="Retail value" value={formatMoney(totals.retail)} hint="At selling price" />
              <StatCard label="On hand" value={formatQty(totals.onHand)} hint="Units" />
              <StatCard label="Stock lines" value={formatNumber(rows.length)} />
            </div>

            <Card className="mb-4 overflow-hidden">
              <div className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-800">
                Value by warehouse
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr className="border-b border-slate-200">
                      <th className={TH}>Warehouse</th>
                      <th className={THR}>Lines</th>
                      <th className={THR}>On hand</th>
                      <th className={THR}>Cost value</th>
                      <th className={THR}>Retail value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {byWh.map((w) => (
                      <tr key={w.id} className="hover:bg-slate-50">
                        <td className={TD}>{whName(w.id)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatNumber(w.lines)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatQty(w.onHand)}</td>
                        <td className={`${TDR} font-semibold text-slate-900`}>{formatMoney(w.cost)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatMoney(w.retail)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                <span className="text-sm font-semibold text-slate-800">By product</span>
                {rows.length > valuationRows.length && (
                  <span className="text-xs text-slate-400">Showing top {valuationRows.length} by value</span>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr className="border-b border-slate-200">
                      <th className={TH}>SKU</th>
                      <th className={TH}>Product</th>
                      <th className={TH}>Warehouse</th>
                      <th className={THR}>On hand</th>
                      <th className={THR}>Unit cost</th>
                      <th className={THR}>Cost value</th>
                      <th className={THR}>Retail value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {valuationRows.map((r) => (
                      <tr key={`${r.productId}:${r.warehouseId}`} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{r.sku}</td>
                        <td className={TD}>
                          <div className="max-w-[16rem] truncate" title={r.name}>
                            {r.name}
                          </div>
                        </td>
                        <td className={`${TD} text-slate-600`}>{whName(r.warehouseId)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatQty(r.onHand)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatMoney(r.unitCost)}</td>
                        <td className={`${TDR} font-semibold text-slate-900`}>{formatMoney(r.costValue)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatMoney(r.retailValue)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        ) : tab === "low" ? (
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard
                label="Low-stock lines"
                value={formatNumber(totals.low)}
                tone={totals.low > 0 ? "warning" : "positive"}
                hint="0 < available ≤ reorder point"
              />
            </div>
            {lowRows.length === 0 ? (
              <Card className="p-10 text-center text-sm text-slate-400">
                Nothing is below its reorder point.
              </Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr className="border-b border-slate-200">
                        <th className={TH}>SKU</th>
                        <th className={TH}>Product</th>
                        <th className={TH}>Warehouse</th>
                        <th className={THR}>Available</th>
                        <th className={THR}>Reorder pt</th>
                        <th className={THR}>Deficit</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {lowRows.map((r) => (
                        <tr key={`${r.productId}:${r.warehouseId}`} className="hover:bg-slate-50">
                          <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{r.sku}</td>
                          <td className={TD}>
                            <div className="max-w-[16rem] truncate" title={r.name}>
                              {r.name}
                            </div>
                          </td>
                          <td className={`${TD} text-slate-600`}>{whName(r.warehouseId)}</td>
                          <td className={`${TDR} text-amber-700`}>{formatQty(r.available)}</td>
                          <td className={`${TDR} text-slate-600`}>{formatQty(r.reorderPoint)}</td>
                          <td className={`${TDR} font-semibold text-slate-900`}>
                            {formatQty(Math.max(0, r.reorderPoint - r.available))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </>
        ) : (
          // out of stock
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard
                label="Out-of-stock lines"
                value={formatNumber(totals.out)}
                tone={totals.out > 0 ? "danger" : "positive"}
                hint="Available ≤ 0"
              />
            </div>
            {outRows.length === 0 ? (
              <Card className="p-10 text-center text-sm text-slate-400">Everything is in stock.</Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr className="border-b border-slate-200">
                        <th className={TH}>SKU</th>
                        <th className={TH}>Product</th>
                        <th className={TH}>Warehouse</th>
                        <th className={THR}>On hand</th>
                        <th className={THR}>Reserved</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {outRows.map((r) => (
                        <tr key={`${r.productId}:${r.warehouseId}`} className="hover:bg-slate-50">
                          <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{r.sku}</td>
                          <td className={TD}>
                            <div className="max-w-[16rem] truncate" title={r.name}>
                              {r.name}
                            </div>
                          </td>
                          <td className={`${TD} text-slate-600`}>{whName(r.warehouseId)}</td>
                          <td className={`${TDR} font-semibold text-red-600`}>{formatQty(r.onHand)}</td>
                          <td className={`${TDR} text-slate-600`}>{formatQty(r.reserved)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </>
        ))}

      {/* Stock position: on-hand / reserved / available / in-transit by branch + location */}
      {tab === "position" &&
        (position.isLoading ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner label="Loading stock position…" />
          </div>
        ) : position.isError ? (
          <Card className="p-6 text-sm text-red-700">
            Couldn’t load stock position. {position.error?.message ?? ""}
          </Card>
        ) : !position.data || position.data.rows.length === 0 ? (
          <Card className="p-10 text-center text-sm text-slate-400">No stock to report on.</Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50">
                  <tr className="border-b border-slate-200">
                    <th className={TH}>Branch</th>
                    <th className={TH}>Location</th>
                    <th className={TH}>SKU</th>
                    <th className={TH}>Product</th>
                    <th className={THR}>On hand</th>
                    <th className={THR}>Reserved</th>
                    <th className={THR}>Available</th>
                    <th className={THR}>In transit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {position.data.rows.map((r) => (
                    <tr key={`${r.location_id}:${r.product_id}`} className="hover:bg-slate-50">
                      <td className={`${TD} text-slate-600`}>{r.branch_name ?? "—"}</td>
                      <td className={`${TD} text-slate-600`}>{r.location_name ?? "—"}</td>
                      <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{r.sku}</td>
                      <td className={TD}>
                        <div className="max-w-[16rem] truncate" title={r.name ?? ""}>{r.name}</div>
                      </td>
                      <td className={`${TDR} text-slate-700`}>{formatQty(r.on_hand)}</td>
                      <td className={`${TDR} text-amber-700`}>{formatQty(r.reserved)}</td>
                      <td className={`${TDR} font-semibold text-slate-900`}>{formatQty(r.available)}</td>
                      <td className={`${TDR} ${Number(r.in_transit) > 0 ? "text-indigo-700" : "text-slate-400"}`}>
                        {Number(r.in_transit) > 0 ? formatQty(r.in_transit) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="px-4 py-3 text-xs text-slate-400">
              Available = on-hand − reserved − damaged. In-transit = issued-but-not-yet-received transfers
              inbound to the location.
            </p>
          </Card>
        ))}

      {/* Movers */}
      {tab === "movers" &&
        (!canMovers ? (
          <Card className="p-6 text-sm text-slate-500">
            Movers analysis runs the reorder engine, which needs the “run reorder” permission.
          </Card>
        ) : movers.isLoading ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner label="Evaluating demand…" />
          </div>
        ) : movers.isError ? (
          <Card className="p-6 text-sm text-red-700">
            Couldn’t compute movers. {movers.error?.message ?? ""}
          </Card>
        ) : (
          <>
            <div className="mb-4 flex items-center gap-2">
              <Button
                variant={moversDir === "fast" ? "primary" : "secondary"}
                onClick={() => setMoversDir("fast")}
              >
                Fast movers
              </Button>
              <Button
                variant={moversDir === "slow" ? "primary" : "secondary"}
                onClick={() => setMoversDir("slow")}
              >
                Slow movers
              </Button>
              <span className="ml-2 text-xs text-slate-400">
                By average monthly sales · top {moverRows.length}
              </span>
            </div>
            {moverRows.length === 0 ? (
              <Card className="p-10 text-center text-sm text-slate-400">No demand data available.</Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr className="border-b border-slate-200">
                        <th className={TH}>SKU</th>
                        <th className={TH}>Product</th>
                        <th className={THR}>Avg monthly</th>
                        <th className={THR}>Avg daily</th>
                        <th className={THR}>Available</th>
                        <th className={THR}>Months of cover</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {moverRows.map((m) => {
                        const cover = m.avgMonthly > 0 ? m.available / m.avgMonthly : null;
                        return (
                          <tr key={m.productId} className="hover:bg-slate-50">
                            <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{m.sku}</td>
                            <td className={TD}>
                              <div className="max-w-[18rem] truncate" title={m.name}>
                                {m.name}
                              </div>
                            </td>
                            <td className={`${TDR} font-semibold text-slate-900`}>
                              {formatQty(m.avgMonthly)}
                            </td>
                            <td className={`${TDR} text-slate-600`}>{formatQty(m.avgDaily)}</td>
                            <td className={`${TDR} text-slate-600`}>{formatQty(m.available)}</td>
                            <td className={`${TDR} text-slate-600`}>
                              {cover === null ? (
                                <span className="text-slate-400">no sales</span>
                              ) : (
                                cover.toFixed(1)
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
            {movers.generatedAt && (
              <p className="mt-3 text-xs text-slate-400">
                Demand evaluated over a 90-day window.
              </p>
            )}
          </>
        ))}

      {/* Supplier performance */}
      {tab === "suppliers" &&
        (supplierPerf.isLoading ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner label="Scoring suppliers…" />
          </div>
        ) : supplierPerf.isError ? (
          <Card className="p-6 text-sm text-red-700">
            Couldn’t load supplier performance. {supplierPerf.error?.message ?? ""}
          </Card>
        ) : !supplierPerf.data || supplierPerf.data.suppliers.length === 0 ? (
          <Card className="p-10 text-center text-sm text-slate-400">No suppliers to report on.</Card>
        ) : (
          <>
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr className="border-b border-slate-200">
                      <th className={TH}>Supplier</th>
                      <th className={THR}>POs</th>
                      <th className={THR}>Received</th>
                      <th className={THR}>On-time</th>
                      <th className={THR}>Avg lead (days)</th>
                      <th className={THR}>Fill rate</th>
                      <th className={TH}>Last order</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {supplierPerf.data.suppliers.map((s) => (
                      <tr key={s.supplier_id} className="hover:bg-slate-50">
                        <td className={TD}>
                          <div className="font-medium">{s.supplier_name}</div>
                          <div className="text-xs text-slate-400">
                            default lead {s.default_lead_time_days}d
                          </div>
                        </td>
                        <td className={`${TDR} text-slate-600`}>{formatNumber(s.po_count)}</td>
                        <td className={`${TDR} text-slate-600`}>{formatNumber(s.received_po_count)}</td>
                        <td className={`${TDR} ${pctTone(s.on_time_rate)}`}>{pct(s.on_time_rate)}</td>
                        <td className={`${TDR} text-slate-600`}>
                          {s.avg_lead_time_days === null ? "—" : s.avg_lead_time_days.toFixed(1)}
                        </td>
                        <td className={`${TDR} ${pctTone(s.fill_rate)}`}>{pct(s.fill_rate)}</td>
                        <td className={`${TD} text-slate-500`}>
                          {s.last_order_at ? formatDate(s.last_order_at) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <p className="mt-3 text-xs text-slate-400">
              On-time and lead time are measured over fully received POs in the last{" "}
              {supplierPerf.data.window_days} days; fill rate is received ÷ ordered across active POs.
            </p>
          </>
        ))}

      {/* Aging */}
      {tab === "aging" &&
        (aging.isLoading ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner label="Reconstructing stock layers…" />
          </div>
        ) : aging.isError ? (
          <Card className="p-6 text-sm text-red-700">
            Couldn’t compute aging. {aging.error?.message ?? ""}
          </Card>
        ) : !aging.data || aging.data.items.length === 0 ? (
          <Card className="p-10 text-center text-sm text-slate-400">No on-hand stock to age.</Card>
        ) : (
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              {aging.data.buckets.map((b) => (
                <StatCard
                  key={b.label}
                  label={`${b.label} days`}
                  value={formatMoney(b.cost_value)}
                  hint={`${formatQty(b.qty)} units`}
                  tone={b.label === "90+" && Number(b.qty) > 0 ? "warning" : "default"}
                />
              ))}
            </div>
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr className="border-b border-slate-200">
                      <th className={TH}>SKU</th>
                      <th className={TH}>Product</th>
                      <th className={TH}>Warehouse</th>
                      <th className={THR}>On hand</th>
                      {BUCKET_LABELS.map((l) => (
                        <th key={l} className={THR}>
                          {l}
                        </th>
                      ))}
                      <th className={THR}>Cost value</th>
                      <th className={TH}>Oldest</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {aging.data.items.map((it) => (
                      <tr key={`${it.product_id}:${it.warehouse_id}`} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{it.sku}</td>
                        <td className={TD}>
                          <div className="max-w-[16rem] truncate" title={it.name}>
                            {it.name}
                          </div>
                        </td>
                        <td className={`${TD} text-slate-600`}>{whName(it.warehouse_id)}</td>
                        <td className={`${TDR} text-slate-700`}>{formatQty(it.on_hand)}</td>
                        {BUCKET_LABELS.map((l) => {
                          const q = Number(it.bucket_qty[l] ?? 0);
                          return (
                            <td
                              key={l}
                              className={`${TDR} ${l === "90+" && q > 0 ? "text-amber-700" : "text-slate-500"}`}
                            >
                              {q ? formatQty(it.bucket_qty[l]) : "—"}
                            </td>
                          );
                        })}
                        <td className={`${TDR} font-semibold text-slate-900`}>{formatMoney(it.cost_value)}</td>
                        <td className={`${TD} text-slate-500`}>
                          {it.oldest_received_at ? formatDate(it.oldest_received_at) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <p className="mt-3 text-xs text-slate-400">
              Layers reconstructed from the movement ledger (FIFO). Reserved and damaged units are
              excluded.
            </p>
          </>
        ))}
    </div>
  );
}
