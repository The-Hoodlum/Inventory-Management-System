// Day book / cash position — for a chosen day or month, per branch: opening cash, money in,
// expenses out, handovers out and closing cash (closing = opening + money in - expenses -
// handovers; transfers between a branch's own accounts net to zero). Downloadable as CSV
// (client) + PDF (server), consistent with the sales daily/monthly report. Needs finance.read.
import { useQuery } from "@tanstack/react-query";
import { Download, FileText } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { type DayBook, downloadFinancePdf, financeApi } from "@/lib/finance";
import { formatMoney } from "@/lib/format";

const zmw = (v: string | number) => formatMoney(Number(v), "ZMW");

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildCsv(b: DayBook): string {
  const line = (r: DayBook["rows"][number]) => [
    r.branch_name ?? "", Number(r.opening).toFixed(2), Number(r.money_in).toFixed(2),
    Number(r.expenses).toFixed(2), Number(r.handovers).toFixed(2), Number(r.closing).toFixed(2),
  ];
  const rows: unknown[][] = [
    ["Day book / cash position", b.period === "daily" ? "Daily" : "Monthly"],
    ["Period", b.label],
    [],
    ["Branch", "Opening", "Money in", "Expenses", "Handovers", "Closing"],
    ...b.rows.map(line),
    ["All branches", ...line(b.totals).slice(1)],
  ];
  return rows.map((r) => r.map(csvCell).join(",")).join("\n");
}

export default function FinanceDayBookPage() {
  const today = new Date().toISOString().slice(0, 10);
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [day, setDay] = useState(today);
  const [month, setMonth] = useState(today.slice(0, 7));
  const date = period === "daily" ? day : `${month}-01`;

  const q = useQuery({
    queryKey: ["finance-day-book", period, date],
    queryFn: () => financeApi.dayBook({ period, date }),
  });
  const b = q.data;
  const csv = useMemo(() => (b ? buildCsv(b) : ""), [b]);

  function exportCsv() {
    if (!b) return;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `day-book-${b.period}-${b.label}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <PageHeader
        title="Day Book / Cash Position"
        description="Opening cash, money in, expenses, handovers and closing cash for a day or month, per branch. Closing = opening + money in − expenses − handovers."
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" disabled={!b} onClick={exportCsv}><Download className="h-4 w-4" /> CSV</Button>
            <Button variant="secondary" disabled={!b} onClick={() => downloadFinancePdf(financeApi.dayBookPdfPath({ period, date }), `day-book-${b?.label}.pdf`)}>
              <FileText className="h-4 w-4" /> PDF
            </Button>
          </div>
        }
      />

      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Period</label>
            <div className="inline-flex rounded-lg border border-line p-0.5">
              {(["daily", "monthly"] as const).map((p) => (
                <button key={p} onClick={() => setPeriod(p)}
                  className={`rounded-md px-3 py-1 text-sm capitalize ${period === p ? "bg-brand-600 text-white" : "text-muted hover:bg-canvas"}`}>{p}</button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">{period === "daily" ? "Day" : "Month"}</label>
            {period === "daily"
              ? <input type="date" className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content" value={day} max={today} onChange={(e) => setDay(e.target.value)} />
              : <input type="month" className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content" value={month} max={today.slice(0, 7)} onChange={(e) => setMonth(e.target.value)} />}
          </div>
          {q.isFetching && <Spinner />}
        </div>
      </Card>

      <Card className="overflow-hidden">
        {q.isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : !b || b.rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-subtle">No cash activity for {b?.label ?? "this period"}.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line bg-canvas text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-2.5 font-medium">Branch</th>
                  <th className="px-4 py-2.5 text-right font-medium">Opening</th>
                  <th className="px-4 py-2.5 text-right font-medium">Money in</th>
                  <th className="px-4 py-2.5 text-right font-medium">Expenses</th>
                  <th className="px-4 py-2.5 text-right font-medium">Handovers</th>
                  <th className="px-4 py-2.5 text-right font-medium">Closing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {b.rows.map((r) => (
                  <tr key={r.branch_id ?? "none"} className="hover:bg-canvas">
                    <td className="px-4 py-2.5 text-content">{r.branch_name ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{zmw(r.opening)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-emerald-700">{zmw(r.money_in)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-red-700">{zmw(r.expenses)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-red-700">{zmw(r.handovers)}</td>
                    <td className="px-4 py-2.5 text-right font-mono font-medium text-content">{zmw(r.closing)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-strong bg-canvas font-semibold">
                  <td className="px-4 py-2.5 text-content">All branches</td>
                  <td className="px-4 py-2.5 text-right font-mono">{zmw(b.totals.opening)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-emerald-700">{zmw(b.totals.money_in)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-red-700">{zmw(b.totals.expenses)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-red-700">{zmw(b.totals.handovers)}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{zmw(b.totals.closing)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
