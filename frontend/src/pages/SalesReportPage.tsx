// Daily / Monthly sales report — what we sold in a day or month (invoiced transactions,
// in frozen ZMW): line detail (parts by SKU+qty, bikes by chassis+model), net/VAT/gross,
// the payment breakdown by method, and collected/outstanding totals. Scoped to the user's
// branch(es). Downloadable as CSV. Sourced from the one server-side aggregation
// (/reports/sales-summary) — same disjoint no-double-count invoice data as the Sales Log.
import { Download } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { formatDate, formatMoney, titleCase } from "@/lib/format";
import { useBranches } from "@/lib/refdata";
import { useSalesSummary } from "@/lib/serverReports";
import type { SalesSummaryReport } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const zmw = (n: number) => formatMoney(n, "ZMW");

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildCsv(rep: SalesSummaryReport, branchName: string): string {
  const rows: unknown[][] = [
    ["Sales report", rep.period === "daily" ? "Daily" : "Monthly"],
    ["Period", rep.label],
    ["Branch", branchName],
    ["Generated", new Date().toISOString()],
    [],
    ["Date", "Type", "Item", "Ref", "Qty", "Net (ZMW)", "VAT (ZMW)", "Gross (ZMW)", "Invoice", "Branch"],
    ...rep.lines.map((l) => [
      l.date, l.kind === "bike" ? "Bike" : "Part", l.description ?? "", l.ref, l.qty,
      l.net.toFixed(2), l.vat.toFixed(2), l.gross.toFixed(2), l.invoice_number, l.branch_name ?? "",
    ]),
    [],
    ["Totals", "", "", "", "", rep.net_total.toFixed(2), rep.vat_total.toFixed(2), rep.gross_total.toFixed(2)],
    ["Collected (ZMW)", rep.collected_total.toFixed(2)],
    ["Outstanding (ZMW)", rep.outstanding_total.toFixed(2)],
    [],
    ["Payments by method", "Amount (ZMW)"],
    ...rep.payments.map((p) => [titleCase(p.method.replace(/_/g, " ")), p.amount.toFixed(2)]),
  ];
  return rows.map((r) => r.map(csvCell).join(",")).join("\n");
}

export default function SalesReportPage() {
  const { user } = useAuth();
  const branches = useBranches();
  const allowed = user?.accessible_branch_ids ?? [];
  const branchOptions = allowed.length ? branches.list.filter((b) => allowed.includes(b.id)) : branches.list;

  const today = new Date().toISOString().slice(0, 10);
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [day, setDay] = useState(today);
  const [month, setMonth] = useState(today.slice(0, 7));
  const [branchId, setBranchId] = useState("");

  const date = period === "daily" ? day : `${month}-01`;
  const q = useSalesSummary(period, date, branchId);
  const rep = q.data;
  const branchName = branchOptions.find((b) => b.id === branchId)?.name ?? "All branches";

  const csv = useMemo(() => (rep ? buildCsv(rep, branchName) : ""), [rep, branchName]);
  function exportCsv() {
    if (!rep) return;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sales-report-${rep.period}-${rep.label}${branchId ? `-${branchName}` : ""}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <PageHeader
        title="Daily / Monthly Report"
        description="What was sold in a day or month — line detail, net/VAT/gross, and the payment breakdown by method. Downloadable as CSV."
        actions={
          <Button variant="secondary" disabled={!rep || rep.lines.length === 0} onClick={exportCsv}>
            <Download className="h-4 w-4" /> Download CSV
          </Button>
        }
      />

      {/* Controls */}
      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Period</label>
            <div className="inline-flex rounded-lg border border-slate-300 p-0.5">
              {(["daily", "monthly"] as const).map((p) => (
                <button key={p} onClick={() => setPeriod(p)}
                  className={`rounded-md px-3 py-1 text-sm capitalize ${period === p ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">{period === "daily" ? "Day" : "Month"}</label>
            {period === "daily" ? (
              <input type="date" value={day} max={today} onChange={(e) => setDay(e.target.value)} className={INPUT} />
            ) : (
              <input type="month" value={month} max={today.slice(0, 7)} onChange={(e) => setMonth(e.target.value)} className={INPUT} />
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Branch</label>
            <select value={branchId} onChange={(e) => setBranchId(e.target.value)} className={INPUT}>
              {allowed.length !== 1 && <option value="">All my branches</option>}
              {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          {q.isFetching && <Spinner />}
        </div>
      </Card>

      {/* Totals */}
      {rep && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
          <TotalCard label="Gross" value={zmw(rep.gross_total)} strong />
          <TotalCard label="Net" value={zmw(rep.net_total)} />
          <TotalCard label="VAT" value={zmw(rep.vat_total)} />
          <TotalCard label="Collected" value={zmw(rep.collected_total)} />
          <TotalCard label="Outstanding" value={zmw(rep.outstanding_total)} tone={rep.outstanding_total > 0 ? "amber" : undefined} />
        </div>
      )}

      {/* Payment breakdown */}
      {rep && rep.payments.length > 0 && (
        <Card className="mb-4 p-4">
          <div className="mb-2 text-sm font-semibold text-slate-800">Payments by method</div>
          <div className="flex flex-wrap gap-2">
            {rep.payments.map((p) => (
              <span key={p.method} className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
                {titleCase(p.method.replace(/_/g, " "))}: <span className="font-mono font-medium">{zmw(p.amount)}</span>
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* Lines */}
      <Card className="overflow-hidden">
        {q.isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : q.isError ? (
          <div className="p-6 text-sm text-red-700">Couldn’t load the report.</div>
        ) : !rep || rep.lines.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            No sales for {period === "daily" ? formatDate(date) : month}.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Date</th>
                  <th className="px-4 py-2.5 font-medium">Type</th>
                  <th className="px-4 py-2.5 font-medium">Item</th>
                  <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                  <th className="px-4 py-2.5 text-right font-medium">Net</th>
                  <th className="px-4 py-2.5 text-right font-medium">VAT</th>
                  <th className="px-4 py-2.5 text-right font-medium">Gross</th>
                  <th className="px-4 py-2.5 font-medium">Invoice</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rep.lines.map((l, i) => (
                  <tr key={`${l.invoice_number}-${l.ref}-${i}`} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 text-slate-500">{formatDate(l.date)}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex rounded-pill px-2 py-0.5 text-2xs font-medium ${l.kind === "bike" ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-600"}`}>
                        {l.kind === "bike" ? "Bike" : "Part"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {l.description ?? "—"}
                      <span className="ml-1 font-mono text-xs text-slate-400">{l.ref}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-slate-600">{l.qty}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-slate-600">{zmw(l.net)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-slate-600">{zmw(l.vat)}</td>
                    <td className="px-4 py-2.5 text-right font-mono font-medium text-slate-900">{zmw(l.gross)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-400">{l.invoice_number}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="mt-3 text-xs text-slate-400">
        Invoiced transactions only, in frozen ZMW (each invoice counted once — no double-count).
        Payments are those recorded against the period’s invoices.
      </p>
    </div>
  );
}

function TotalCard({ label, value, strong, tone }: { label: string; value: string; strong?: boolean; tone?: "amber" }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={`mt-1 font-mono ${strong ? "text-xl font-semibold text-slate-900" : "text-lg " + (tone === "amber" ? "text-amber-700" : "text-slate-800")}`}>
        {value}
      </div>
    </Card>
  );
}
