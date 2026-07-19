// Account statement — every movement on an account (date, description, source, in, out,
// RUNNING BALANCE) for a date range, with opening + closing. Branch cash statements show
// handovers as OUT movements with the receiver's name in the description, so "where did the
// cash go" is answerable here. Downloadable as CSV (client) + PDF (server). Needs finance.read.
import { useQuery } from "@tanstack/react-query";
import { Download, FileText } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { type AccountStatement, downloadFinancePdf, financeApi } from "@/lib/finance";
import { formatDate, formatMoney } from "@/lib/format";

const INPUT =
  "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const zmw = (v: string | number) => formatMoney(Number(v), "ZMW");

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildCsv(s: AccountStatement): string {
  const rows: unknown[][] = [
    ["Account statement", s.account_name ?? ""],
    ["Period", `${s.date_from} to ${s.date_to}`],
    ["Opening balance", Number(s.opening_balance).toFixed(2)],
    [],
    ["Date", "Description", "Category", "In", "Out", "Running balance"],
    ...s.rows.map((r) => [
      r.occurred_at.slice(0, 10), r.description ?? "", r.category ?? "",
      Number(r.in_amount).toFixed(2), Number(r.out_amount).toFixed(2), Number(r.running_balance).toFixed(2),
    ]),
    [],
    ["Totals", "", "", Number(s.total_in).toFixed(2), Number(s.total_out).toFixed(2), ""],
    ["Closing balance", Number(s.closing_balance).toFixed(2)],
  ];
  return rows.map((r) => r.map(csvCell).join(",")).join("\n");
}

export default function FinanceStatementPage() {
  const [sp, setSp] = useSearchParams();
  const today = new Date().toISOString().slice(0, 10);
  const monthStart = today.slice(0, 8) + "01";
  const [accountId, setAccountId] = useState(sp.get("account") ?? "");
  const [from, setFrom] = useState(monthStart);
  const [to, setTo] = useState(today);

  const accountsQ = useQuery({ queryKey: ["finance-accounts", "all"], queryFn: () => financeApi.listAccounts() });
  const stmtQ = useQuery({
    queryKey: ["finance-statement", accountId, from, to],
    queryFn: () => financeApi.statement(accountId, { date_from: from, date_to: to }),
    enabled: !!accountId,
  });
  const s = stmtQ.data;

  const csv = useMemo(() => (s ? buildCsv(s) : ""), [s]);
  function exportCsv() {
    if (!s) return;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `statement-${s.account_name}-${s.date_from}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <PageHeader
        title="Account Statement"
        description="Every movement on an account with a running balance. Handovers appear as OUT with the receiver's name, so cash is fully traceable."
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" disabled={!s || s.rows.length === 0} onClick={exportCsv}><Download className="h-4 w-4" /> CSV</Button>
            <Button variant="secondary" disabled={!accountId} onClick={() => downloadFinancePdf(financeApi.statementPdfPath(accountId, { date_from: from, date_to: to }), `statement-${s?.account_name ?? accountId}.pdf`)}>
              <FileText className="h-4 w-4" /> PDF
            </Button>
          </div>
        }
      />

      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Account</label>
            <select className={INPUT} value={accountId} onChange={(e) => { setAccountId(e.target.value); setSp(e.target.value ? { account: e.target.value } : {}); }}>
              <option value="">Select an account…</option>
              {(accountsQ.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
          <div><label className="mb-1 block text-xs font-medium text-muted">From</label><input type="date" className={INPUT} value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></div>
          <div><label className="mb-1 block text-xs font-medium text-muted">To</label><input type="date" className={INPUT} value={to} max={today} onChange={(e) => setTo(e.target.value)} /></div>
          {stmtQ.isFetching && <Spinner />}
        </div>
      </Card>

      {s && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label="Opening" value={zmw(s.opening_balance)} />
          <Tile label="Total in" value={zmw(s.total_in)} tone="green" />
          <Tile label="Total out" value={zmw(s.total_out)} tone="red" />
          <Tile label="Closing" value={zmw(s.closing_balance)} strong />
        </div>
      )}

      <Card className="overflow-hidden">
        {!accountId ? (
          <div className="p-10 text-center text-sm text-subtle">Pick an account to see its statement.</div>
        ) : stmtQ.isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : !s || s.rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-subtle">No movements in this period.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line bg-canvas text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-2.5 font-medium">Date</th>
                  <th className="px-4 py-2.5 font-medium">Description</th>
                  <th className="px-4 py-2.5 text-right font-medium">In</th>
                  <th className="px-4 py-2.5 text-right font-medium">Out</th>
                  <th className="px-4 py-2.5 text-right font-medium">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {s.rows.map((r) => (
                  <tr key={r.id} className="hover:bg-canvas">
                    <td className="px-4 py-2.5 text-muted">{formatDate(r.occurred_at)}</td>
                    <td className="px-4 py-2.5 text-content">{r.description ?? r.category ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-emerald-700">{Number(r.in_amount) ? zmw(r.in_amount) : ""}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-red-700">{Number(r.out_amount) ? zmw(r.out_amount) : ""}</td>
                    <td className="px-4 py-2.5 text-right font-mono font-medium text-content">{zmw(r.running_balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Tile({ label, value, strong, tone }: { label: string; value: string; strong?: boolean; tone?: "green" | "red" }) {
  const color = tone === "green" ? "text-emerald-700" : tone === "red" ? "text-red-700" : "text-content";
  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={`mt-1 font-mono ${strong ? "text-xl font-semibold" : "text-lg"} ${color}`}>{value}</div>
    </Card>
  );
}
