// Finance payment setup — map each sales payment method to the finance account it posts
// to, per branch. When a payment is recorded on a mapped branch, finance posts one IN
// movement per line to the mapped account (money-in is read from the sale, never re-keyed).
// Once a branch has ANY mapping it's "on": an unmapped method then fails the sale loudly.
// View needs finance.read; editing needs finance.account.manage.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  PAYMENT_METHODS,
  PAYMENT_METHOD_LABELS,
  type PaymentMethod,
  financeApi,
} from "@/lib/finance";
import { useBranches } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function FinancePaymentSetupPage() {
  const { user, hasPermission } = useAuth();
  const canManage = hasPermission("finance.account.manage");
  const branches = useBranches();
  const allowed = user?.accessible_branch_ids ?? [];
  const branchOptions = allowed.length
    ? branches.list.filter((b) => allowed.includes(b.id))
    : branches.list;

  const [branchId, setBranchId] = useState("");
  const effectiveBranch = branchId || branchOptions[0]?.id || "";

  const accountsQ = useQuery({
    queryKey: ["finance-accounts", effectiveBranch],
    queryFn: () => financeApi.listAccounts({ branch_id: effectiveBranch, active_only: true }),
    enabled: !!effectiveBranch,
  });
  const mappingsQ = useQuery({
    queryKey: ["finance-mappings"],
    queryFn: () => financeApi.listMappings(),
  });

  const mappingFor = useMemo(() => {
    const m = new Map<PaymentMethod, { id: string; account_id: string }>();
    for (const row of mappingsQ.data ?? []) {
      if (row.branch_id === effectiveBranch) m.set(row.method, { id: row.id, account_id: row.account_id });
    }
    return m;
  }, [mappingsQ.data, effectiveBranch]);

  const accounts = accountsQ.data ?? [];

  return (
    <div>
      <PageHeader
        title="Payment Setup"
        description="Map each payment method to the account its money lands in, per branch. Recorded payments then post automatically to finance — split payments post to each method's account."
      />

      <Card className="mb-4 p-4">
        <label className="mb-1 block text-xs font-medium text-slate-500">Branch</label>
        <select className={INPUT} value={effectiveBranch} onChange={(e) => setBranchId(e.target.value)}>
          {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        {!canManage && (
          <p className="mt-2 text-xs text-slate-400">You have view-only access to finance setup.</p>
        )}
      </Card>

      <Card className="overflow-hidden">
        {accountsQ.isLoading || mappingsQ.isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-canvas text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 font-medium">Payment method</th>
                <th className="px-4 py-2.5 font-medium">Posts to account</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {PAYMENT_METHODS.map((method) => (
                <MethodRow
                  key={method}
                  method={method}
                  branchId={effectiveBranch}
                  accounts={accounts.map((a) => ({ id: a.id, name: a.name }))}
                  current={mappingFor.get(method)}
                  canManage={canManage}
                />
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <p className="mt-3 text-xs text-slate-400">
        A branch with no mappings doesn’t post to finance. Once you map any method, a payment
        whose method is unmapped is rejected (so money is never silently dropped) — map every
        method the branch actually takes.
      </p>
    </div>
  );
}

function MethodRow({
  method, branchId, accounts, current, canManage,
}: {
  method: PaymentMethod;
  branchId: string;
  accounts: { id: string; name: string }[];
  current?: { id: string; account_id: string };
  canManage: boolean;
}) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async (accountId: string): Promise<void> => {
      if (!accountId) {
        if (current) await financeApi.deleteMapping(current.id);
        return;
      }
      await financeApi.setMapping({ branch_id: branchId, method, account_id: accountId });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["finance-mappings"] }),
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save."),
  });

  return (
    <tr className="hover:bg-canvas">
      <td className="px-4 py-3 font-medium text-content">{PAYMENT_METHOD_LABELS[method]}</td>
      <td className="px-4 py-3">
        <select
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-60"
          value={current?.account_id ?? ""}
          disabled={!canManage || save.isPending}
          onChange={(e) => { setErr(null); save.mutate(e.target.value); }}
        >
          <option value="">— Not posting —</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        {save.isPending && <span className="ml-2 text-xs text-slate-400">Saving…</span>}
        {err && <span className="ml-2 text-xs text-red-600">{err}</span>}
      </td>
    </tr>
  );
}
