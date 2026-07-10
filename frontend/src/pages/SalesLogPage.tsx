// Unified Sales Log — one report over BOTH revenue streams (spare parts + motorcycles),
// bucketed daily / weekly / monthly and filterable by type, branch and date range. Every
// sale is counted once (parts come from invoice lines, motorcycles from sold units — see
// the backend's shared no-double-count aggregation). Rows drill down into the per-type
// breakdown; the whole view exports to CSV.
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { formatDate, formatNumber } from "@/lib/format";
import { useBranches } from "@/lib/refdata";
import { salesApi } from "@/lib/sales";
import { useSalesLog } from "@/lib/serverReports";
import type { SalesLogGranularity, SalesLogRow, SalesLogType } from "@/types/api";

interface TxnRow { date: string; kind: "Part" | "Bike"; item: string; customer: string; qty: number; amount: number; ref: string; historical: boolean }

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const GRANULARITIES: { value: SalesLogGranularity; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];
const TYPES: { value: SalesLogType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "parts", label: "Spare Parts" },
  { value: "motorcycles", label: "Motorcycles" },
];

const isoDaysAgo = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
const money = (n: number) => formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function toCsv(rows: SalesLogRow[]): string {
  const head = ["Period", "Start", "End", "Units", "Revenue", "Parts revenue", "Motorcycle revenue", "Historical revenue"];
  const rev = (r: SalesLogRow, t: string) => r.components.find((c) => c.type === t)?.revenue ?? 0;
  const lines = rows.map((r) => [
    r.label, r.period_start, r.period_end, r.units, r.revenue,
    rev(r, "parts"), rev(r, "motorcycle_new"), rev(r, "motorcycle_historical"),
  ]);
  return [head, ...lines].map((cols) => cols.join(",")).join("\n");
}

export default function SalesLogPage() {
  const branches = useBranches();
  const [granularity, setGranularity] = useState<SalesLogGranularity>("daily");
  const [type, setType] = useState<SalesLogType>("all");
  const [branchId, setBranchId] = useState("");
  const [dateFrom, setDateFrom] = useState(isoDaysAgo(84));
  const [dateTo, setDateTo] = useState(isoDaysAgo(0));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const [view, setView] = useState<"summary" | "transactions">("summary");

  const q = useSalesLog({ granularity, type, branchId, dateFrom, dateTo });
  const rows = q.data?.rows ?? [];
  const totals = q.data?.totals;

  const txnOn = view === "transactions";
  const partsQ = useQuery({
    queryKey: ["txn-parts", branchId, dateFrom, dateTo],
    queryFn: () => salesApi.listPartsSales({ branch_id: branchId || undefined, date_from: dateFrom, date_to: dateTo, limit: 1000 }),
    enabled: txnOn && type !== "motorcycles",
  });
  const motoQ = useQuery({
    queryKey: ["txn-moto", branchId, dateFrom, dateTo],
    queryFn: () => salesApi.listMotorcycleSales({ branch_id: branchId || undefined, date_from: dateFrom, date_to: dateTo, limit: 1000 }),
    enabled: txnOn && type !== "parts",
  });
  const txns: TxnRow[] = useMemo(() => {
    const out: TxnRow[] = [];
    if (type !== "motorcycles") for (const p of partsQ.data ?? []) out.push({
      date: p.sale_date, kind: "Part", item: `${p.name ?? "—"}${p.sku ? ` (${p.sku})` : ""}`,
      customer: p.customer_name ?? "—", qty: p.qty, amount: p.line_total, ref: p.invoice_number, historical: false });
    if (type !== "parts") for (const m of motoQ.data ?? []) out.push({
      date: m.sale_date ?? "", kind: "Bike", item: `${m.model_name ?? "Motorcycle"} · ${m.chassis_number}`,
      customer: m.customer_name ?? "—", qty: 1, amount: m.revenue, ref: m.invoice_number ?? (m.historical ? "historical" : "—"), historical: m.historical });
    return out.sort((a, b) => (b.date > a.date ? 1 : b.date < a.date ? -1 : 0));
  }, [partsQ.data, motoQ.data, type]);
  const txnLoading = (partsQ.isFetching && type !== "motorcycles") || (motoQ.isFetching && type !== "parts");

  const toggle = (label: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      next.has(label) ? next.delete(label) : next.add(label);
      return next;
    });

  const csv = useMemo(() => toCsv(rows), [rows]);
  function exportCsv() {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sales-log-${type}-${granularity}-${dateFrom}_${dateTo}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <PageHeader
        title="Sales Log"
        description="Unified parts + motorcycle sales — summary by period, or the full transaction history."
        actions={
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-300 p-0.5">
              {(["summary", "transactions"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)}
                  className={`rounded-md px-3 py-1 text-sm capitalize ${view === v ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                  {v}
                </button>
              ))}
            </div>
            <Button variant="secondary" disabled={rows.length === 0} onClick={exportCsv}>
              <Download className="h-4 w-4" /> Export CSV
            </Button>
          </div>
        }
      />

      {/* Filters */}
      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Granularity</label>
            <div className="inline-flex rounded-lg border border-slate-300 p-0.5">
              {GRANULARITIES.map((g) => (
                <button
                  key={g.value}
                  onClick={() => setGranularity(g.value)}
                  className={`rounded-md px-3 py-1 text-sm ${
                    granularity === g.value ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {g.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Type</label>
            <select value={type} onChange={(e) => setType(e.target.value as SalesLogType)} className={INPUT}>
              {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Branch</label>
            <select value={branchId} onChange={(e) => setBranchId(e.target.value)} className={INPUT}>
              <option value="">All branches</option>
              {branches.list.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">From</label>
            <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} className={INPUT} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">To</label>
            <input type="date" value={dateTo} min={dateFrom} onChange={(e) => setDateTo(e.target.value)} className={INPUT} />
          </div>
          {q.isFetching && <Spinner />}
        </div>
      </Card>

      {/* Totals */}
      {!txnOn && totals && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <TotalCard label="Total revenue" value={money(totals.revenue)} hint={`${formatNumber(totals.units)} units`} strong />
          <TotalCard label="Spare parts" value={money(totals.parts_revenue)} hint={`${formatNumber(totals.parts_units)} units`} />
          <TotalCard label="Motorcycles" value={money(totals.motorcycle_revenue)} hint={`${formatNumber(totals.motorcycle_units)} units`} />
          <TotalCard label="Motorcycles (historical)" value={money(totals.historical_revenue)} hint={`${formatNumber(totals.historical_units)} units`} />
        </div>
      )}

      {/* Transactions (full history) */}
      {txnOn && (
        <Card className="overflow-hidden">
          {txnLoading && txns.length === 0 ? (
            <div className="flex h-40 items-center justify-center"><Spinner label="Loading transactions…" /></div>
          ) : txns.length === 0 ? (
            <div className="p-10 text-center text-sm text-slate-400">No sales in this range.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2.5 font-medium">Date</th>
                    <th className="px-4 py-2.5 font-medium">Type</th>
                    <th className="px-4 py-2.5 font-medium">Item</th>
                    <th className="px-4 py-2.5 font-medium">Customer</th>
                    <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                    <th className="px-4 py-2.5 text-right font-medium">Amount</th>
                    <th className="px-4 py-2.5 font-medium">Ref</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {txns.map((t, i) => (
                    <tr key={i} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 text-slate-500">{t.date ? formatDate(t.date) : "—"}</td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex rounded-pill px-2 py-0.5 text-2xs font-medium ${t.kind === "Bike" ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-600"}`}>
                          {t.kind}{t.historical ? " · hist." : ""}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-slate-700">{t.item}</td>
                      <td className="px-4 py-2.5 text-slate-600">{t.customer}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-600">{formatNumber(t.qty)}</td>
                      <td className="px-4 py-2.5 text-right font-mono font-medium text-slate-900">{money(t.amount)}</td>
                      <td className="px-4 py-2.5 font-mono text-xs text-slate-400">{t.ref}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Period table */}
      {!txnOn && (
      <Card className="overflow-hidden">
        {q.isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading sales…" /></div>
        ) : q.isError ? (
          <div className="p-6 text-sm text-red-700">Couldn’t load the sales log.</div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">No sales in this range.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Period</th>
                <th className="px-4 py-2.5 font-medium">Range</th>
                <th className="px-4 py-2.5 text-right font-medium">Units</th>
                <th className="px-4 py-2.5 text-right font-medium">Revenue</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => {
                const open = expanded.has(r.label);
                return (
                  <Fragment key={r.label}>
                    <tr
                      className="cursor-pointer hover:bg-slate-50"
                      onClick={() => toggle(r.label)}
                    >
                      <td className="px-4 py-3 font-medium text-slate-800">
                        <span className="inline-flex items-center gap-1.5">
                          {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
                          {r.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {formatDate(r.period_start)}
                        {r.period_end !== r.period_start ? ` – ${formatDate(r.period_end)}` : ""}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-700">{formatNumber(r.units)}</td>
                      <td className="px-4 py-3 text-right font-mono font-medium text-slate-900">{money(r.revenue)}</td>
                      <td className="px-4 py-3" />
                    </tr>
                    {open &&
                      r.components.map((c) => (
                        <tr key={`${r.label}-${c.type}`} className="bg-slate-50/60 text-slate-600">
                          <td className="px-4 py-2 pl-11 text-xs">{c.label}</td>
                          <td className="px-4 py-2" />
                          <td className="px-4 py-2 text-right font-mono text-xs">{formatNumber(c.units)}</td>
                          <td className="px-4 py-2 text-right font-mono text-xs">{money(c.revenue)}</td>
                          <td className="px-4 py-2" />
                        </tr>
                      ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      )}

      <p className="mt-3 text-xs text-slate-400">
        Revenue is summed in stored amounts and is not currency-converted (spare parts and
        motorcycles may be priced in different currencies).
      </p>
    </div>
  );
}

function TotalCard({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={`mt-1 font-mono ${strong ? "text-2xl font-semibold text-slate-900" : "text-xl text-slate-800"}`}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
    </Card>
  );
}
