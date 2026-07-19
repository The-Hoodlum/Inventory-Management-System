// Finance dashboard — current balance per account (KPI cards) plus, for the selected
// period: money in (from recorded sale payments), expenses out, handovers out and the net
// movement. Reads the one finance ledger (single source), branch-scoped. Needs finance.read.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Card, Spinner } from "@/components/ui";
import { ACCOUNT_TYPE_LABELS, financeApi } from "@/lib/finance";
import { formatMoney } from "@/lib/format";
import { useBranches } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const zmw = (v: string | number) => formatMoney(Number(v), "ZMW");

export default function FinanceDashboardPage() {
  const { user } = useAuth();
  const branches = useBranches();
  const allowed = user?.accessible_branch_ids ?? [];
  const branchOptions = allowed.length ? branches.list.filter((b) => allowed.includes(b.id)) : branches.list;

  const today = new Date().toISOString().slice(0, 10);
  const monthStart = today.slice(0, 8) + "01";
  const [from, setFrom] = useState(monthStart);
  const [to, setTo] = useState(today);
  const [branchId, setBranchId] = useState("");

  const q = useQuery({
    queryKey: ["finance-dashboard", from, to, branchId],
    queryFn: () => financeApi.dashboard({ date_from: from, date_to: to, branch_id: branchId || undefined }),
  });
  const d = q.data;

  return (
    <div>
      <PageHeader
        title="Finance Dashboard"
        description="Current balance per account, and money in / out for the selected period. Money in is read from recorded sale payments — it reconciles with sales."
      />

      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <Labeled label="From"><input type="date" className={INPUT} value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></Labeled>
          <Labeled label="To"><input type="date" className={INPUT} value={to} max={today} onChange={(e) => setTo(e.target.value)} /></Labeled>
          <Labeled label="Branch">
            <select className={INPUT} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
              {allowed.length !== 1 && <option value="">All my branches</option>}
              {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </Labeled>
          {q.isFetching && <Spinner />}
        </div>
      </Card>

      {/* Period summary */}
      {d && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label="Money in" value={zmw(d.money_in)} tone="green" />
          <Tile label="Expenses out" value={zmw(d.expenses_out)} tone="red" />
          <Tile label="Handovers out" value={zmw(d.handovers_out)} />
          <Tile label="Net movement" value={zmw(d.net_movement)} strong tone={Number(d.net_movement) < 0 ? "red" : "green"} />
        </div>
      )}

      {/* Balances per account */}
      <Card className="mb-4 p-4">
        <div className="mb-3 text-sm font-semibold text-content">Balances by account</div>
        {q.isLoading ? (
          <div className="flex h-24 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : !d || d.accounts.length === 0 ? (
          <p className="py-6 text-center text-sm text-subtle">No accounts in scope.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.accounts.map((a) => (
              <div key={a.id} className="rounded-card border border-line p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-content">{a.name}</span>
                  <span className="text-2xs uppercase tracking-wide text-subtle">{ACCOUNT_TYPE_LABELS[a.type]}</span>
                </div>
                <div className="mt-1 font-mono text-lg font-semibold text-content">{zmw(a.balance)}</div>
                <div className="text-2xs text-subtle">{a.branch_name ?? "Tenant-wide"}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Money in by account */}
      {d && d.money_in_by_account.length > 0 && (
        <Card className="p-4">
          <div className="mb-2 text-sm font-semibold text-content">Money in by account</div>
          <div className="flex flex-wrap gap-2">
            {d.money_in_by_account.map((m) => (
              <span key={m.account_id} className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
                {m.account_name}: <span className="font-mono font-medium">{zmw(m.amount)}</span>
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-muted">{label}</label>
      {children}
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
