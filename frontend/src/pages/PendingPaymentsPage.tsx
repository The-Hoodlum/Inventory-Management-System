// Pending Payments (accounts receivable): every invoice that still owes money — unpaid,
// partially paid or overdue — so staff can see who to chase and collect. Data comes from
// GET /sales/invoices/outstanding (balance computed server-side, voided/paid excluded;
// both parts and bike invoices). Each row opens the shared PaymentModal to settle, which
// invalidates the ["sales"] query tree so this list refreshes on payment.
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CircleDollarSign, Wallet } from "lucide-react";
import { useMemo, useState } from "react";

import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { PaymentModal } from "@/components/PaymentModal";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { formatDate, formatMoney } from "@/lib/format";
import { salesApi } from "@/lib/sales";

const TH = "px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-slate-500";
const THR = "px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-slate-500";
const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

/** Whole days since an ISO date (clamped at 0). */
function ageDays(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86_400_000));
}

export default function PendingPaymentsPage() {
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canPay = hasPermission("sales.payment");
  const canImport = hasPermission("data.import");
  const [search, setSearch] = useState("");
  const [payInvoice, setPayInvoice] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["sales", "outstanding"],
    queryFn: () => salesApi.listOutstandingInvoices(),
  });

  const term = search.trim().toLowerCase();
  const rows = useMemo(() => {
    const all = q.data ?? [];
    if (!term) return all;
    return all.filter(
      (i) =>
        (i.customer_name ?? "").toLowerCase().includes(term) ||
        i.invoice_number.toLowerCase().includes(term),
    );
  }, [q.data, term]);

  const totalOutstanding = rows.reduce((s, i) => s + (i.balance || 0), 0);

  return (
    <div>
      <PageHeader
        title="Pending Payments"
        description="Invoices that still owe money — unpaid, partially paid or overdue. Record a payment to collect and clear the balance."
        actions={canImport && (
          <Button variant="secondary" onClick={() => navigate("/sales/pending-payments/import")}>
            Import pending bikes
          </Button>
        )}
      />

      {/* Summary */}
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <SummaryTile icon={<CircleDollarSign className="h-5 w-5" />} label="Total outstanding"
          value={formatMoney(totalOutstanding, "ZMW")} tone="amber" />
        <SummaryTile icon={<Wallet className="h-5 w-5" />} label="Open invoices" value={String(rows.length)} />
        <SummaryTile icon={<AlertCircle className="h-5 w-5" />} label="Oldest"
          value={rows.length ? `${ageDays(rows[0].invoice_date) ?? 0} days` : "—"}
          hint={rows.length ? (rows[0].customer_name ?? "—") : undefined} />
      </div>

      <div className="mb-3">
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by customer or invoice #" className={`${INPUT} w-full max-w-sm`} />
      </div>

      {q.isLoading ? (
        <div className="flex h-40 items-center justify-center"><Spinner label="Loading receivables…" /></div>
      ) : rows.length === 0 ? (
        <Card className="p-10 text-center text-sm text-slate-400">
          {term ? "No invoices match your filter." : "Nothing outstanding — every invoice is settled. 🎉"}
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="border-b border-slate-200">
                  <th className={TH}>Customer</th>
                  <th className={TH}>Invoice #</th>
                  <th className={TH}>Date</th>
                  <th className={THR}>Total (ZMW)</th>
                  <th className={THR}>Paid (ZMW)</th>
                  <th className={THR}>Balance (ZMW)</th>
                  <th className={TH}>Status</th>
                  <th className={THR}>Age</th>
                  <th className={THR} />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((i) => {
                  const age = ageDays(i.invoice_date);
                  return (
                    <tr key={i.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 text-slate-700">{i.customer_name ?? "—"}</td>
                      <td className="px-4 py-3 font-mono text-[13px] font-medium text-slate-700">{i.invoice_number}</td>
                      <td className="px-4 py-3 text-slate-500">{formatDate(i.invoice_date)}</td>
                      <td className="px-4 py-3 text-right font-mono text-slate-600">{formatMoney(i.grand_total_zmw, "ZMW")}</td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-700">{formatMoney(i.amount_paid, "ZMW")}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold text-slate-800">{formatMoney(i.balance, "ZMW")}</td>
                      <td className="px-4 py-3"><StatusBadge status={i.status} /></td>
                      <td className={"px-4 py-3 text-right font-mono " + (age !== null && age > 30 ? "text-red-600" : "text-slate-500")}>
                        {age === null ? "—" : `${age}d`}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" onClick={() => void salesApi.downloadInvoicePdf(i.id, i.invoice_number)}>PDF</Button>
                          {canPay && (
                            <Button variant="secondary" onClick={() => setPayInvoice(i.id)}>Record payment</Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {payInvoice && <PaymentModal invoiceId={payInvoice} onClose={() => setPayInvoice(null)} />}
    </div>
  );
}

function SummaryTile({ icon, label, value, hint, tone }: {
  icon: React.ReactNode; label: string; value: string; hint?: string; tone?: "amber";
}) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <div className={"flex h-10 w-10 items-center justify-center rounded-xl " +
        (tone === "amber" ? "bg-amber-100 text-amber-700" : "bg-brand-100 text-brand-700")}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-slate-500">{label}</div>
        <div className="truncate text-lg font-semibold text-slate-800">{value}</div>
        {hint && <div className="truncate text-xs text-slate-400">{hint}</div>}
      </div>
    </Card>
  );
}
