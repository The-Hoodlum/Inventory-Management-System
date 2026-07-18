// Finance accounts admin — create / edit / deactivate cash, bank, mobile-money and
// custody accounts, branch-scoped. Every account is an append-only ledger; the BALANCE
// shown is DERIVED (opening + IN - OUT) by the server and can never be set here. View
// needs finance.read; create/edit needs finance.account.manage. Accounts are DEACTIVATED,
// never deleted (no delete action exists).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Landmark, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  ACCOUNT_TYPE_LABELS,
  type AccountCreateInput,
  type AccountType,
  type FinanceAccount,
  financeApi,
} from "@/lib/finance";
import { formatMoney } from "@/lib/format";
import { useBranches } from "@/lib/refdata";

const INPUT =
  "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const TYPES: AccountType[] = ["CASH", "BANK", "MOBILE_MONEY", "CUSTODY"];
const money = (v: string | number, ccy: string) => formatMoney(Number(v), ccy);

export default function FinanceAccountsPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("finance.account.manage");
  const [table, setTable] = useState<DataTableState>(initialTableState(50));
  const [modal, setModal] = useState<{ item?: FinanceAccount } | null>(null);

  const { data, isFetching } = useQuery({
    queryKey: ["finance-accounts"],
    queryFn: () => financeApi.listAccounts(),
  });

  const rows = useMemo(() => {
    const all = data ?? [];
    const q = table.search.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        ACCOUNT_TYPE_LABELS[a.type].toLowerCase().includes(q) ||
        (a.branch_name ?? "").toLowerCase().includes(q),
    );
  }, [data, table.search]);

  const columns: Column<FinanceAccount>[] = [
    { key: "name", header: "Account", accessor: (a) => a.name, render: (a) => <b>{a.name}</b> },
    { key: "type", header: "Type", accessor: (a) => ACCOUNT_TYPE_LABELS[a.type] },
    { key: "branch", header: "Branch", accessor: (a) => a.branch_name ?? "Tenant-wide" },
    {
      key: "balance", header: "Balance", align: "right",
      accessor: (a) => Number(a.balance),
      render: (a) => <span className="font-mono font-medium text-content">{money(a.balance, a.currency)}</span>,
    },
    {
      key: "in", header: "Total in", align: "right", defaultHidden: true,
      accessor: (a) => Number(a.total_in), render: (a) => <span className="font-mono text-muted">{money(a.total_in, a.currency)}</span>,
    },
    {
      key: "out", header: "Total out", align: "right", defaultHidden: true,
      accessor: (a) => Number(a.total_out), render: (a) => <span className="font-mono text-muted">{money(a.total_out, a.currency)}</span>,
    },
    {
      key: "status", header: "Status",
      accessor: (a) => (a.is_active ? "active" : "inactive"),
      render: (a) => <StatusBadge status={a.is_active ? "active" : "inactive"} />,
    },
  ];
  if (canManage) {
    columns.push({
      key: "actions", header: "", align: "right",
      render: (a) => <Button variant="ghost" onClick={() => setModal({ item: a })}>Edit</Button>,
    });
  }

  return (
    <>
      <ListPage<FinanceAccount>
        title="Finance Accounts"
        description="Cash in hand, bank accounts, mobile-money wallets and custody accounts. Each is an append-only ledger — the balance is derived from its movements, never set."
        icon={<Landmark className="h-5 w-5" />}
        actions={canManage ? (
          <Button onClick={() => setModal({})}><Plus className="h-4 w-4" /> New account</Button>
        ) : undefined}
        table={{
          columns,
          rows,
          total: rows.length,
          rowId: (a) => a.id,
          state: table,
          onStateChange: setTable,
          loading: isFetching && !data,
          storageKey: "finance-accounts-table",
          exportName: "finance-accounts",
          emptyTitle: "No accounts yet",
          emptyHint: canManage ? "Create your first cash or bank account to start." : undefined,
        }}
      />
      {modal && <AccountModal item={modal.item} onClose={() => setModal(null)} />}
    </>
  );
}

function AccountModal({ item, onClose }: { item?: FinanceAccount; onClose: () => void }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const branches = useBranches();
  const allowed = user?.accessible_branch_ids ?? [];
  const branchOptions = allowed.length
    ? branches.list.filter((b) => allowed.includes(b.id))
    : branches.list;

  const editing = !!item;
  const [name, setName] = useState(item?.name ?? "");
  const [type, setType] = useState<AccountType>(item?.type ?? "CASH");
  const [branchId, setBranchId] = useState(item?.branch_id ?? "");
  const [currency, setCurrency] = useState(item?.currency ?? "ZMW");
  const [openingBalance, setOpeningBalance] = useState(item?.opening_balance ?? "0");
  const [openingAsOf, setOpeningAsOf] = useState(item?.opening_as_of ?? "");
  const [active, setActive] = useState(item?.is_active ?? true);
  const [err, setErr] = useState<string | null>(null);

  const branchRequired = type !== "CUSTODY";

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        // Only naming + the active flag are editable — never a balance / type / branch.
        return financeApi.updateAccount(item!.id, { name: name.trim(), is_active: active });
      }
      const body: AccountCreateInput = {
        name: name.trim(),
        type,
        branch_id: branchRequired ? branchId || null : branchId || null,
        currency: currency.trim() || "ZMW",
        opening_balance: openingBalance || "0",
        opening_as_of: openingAsOf || null,
      };
      return financeApi.createAccount(body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["finance-accounts"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the account."),
  });

  const canSave =
    name.trim().length > 0 && (editing || !branchRequired || branchId) && !save.isPending;

  return (
    <Modal
      title={editing ? "Edit account" : "New account"}
      size="md"
      onClose={onClose}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>Cancel</Button>
          <Button disabled={!canSave} onClick={() => { setErr(null); save.mutate(); }}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        {editing && (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
            The type, branch, currency and opening balance are fixed once an account exists — a
            balance is derived from movements and can never be re-set. To retire an account,
            switch it to inactive; its ledger and history are kept.
          </p>
        )}
        <Field label="Name *">
          <input className={INPUT} value={name} autoFocus onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Cash in hand — Lusaka" />
        </Field>
        {!editing && (
          <>
            <Field label="Type *">
              <select className={INPUT} value={type} onChange={(e) => setType(e.target.value as AccountType)}>
                {TYPES.map((t) => <option key={t} value={t}>{ACCOUNT_TYPE_LABELS[t]}</option>)}
              </select>
            </Field>
            <Field label={branchRequired ? "Branch *" : "Branch (optional for custody)"}>
              <select className={INPUT} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
                <option value="">{branchRequired ? "Select a branch…" : "Tenant-wide (no branch)"}</option>
                {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Currency">
                <input className={INPUT} value={currency} onChange={(e) => setCurrency(e.target.value)} />
              </Field>
              <Field label="Opening balance">
                <input className={INPUT} type="number" step="0.01" min="0" value={openingBalance}
                  onChange={(e) => setOpeningBalance(e.target.value)} />
              </Field>
            </div>
            <Field label="Opening as of">
              <input className={INPUT} type="date" value={openingAsOf} onChange={(e) => setOpeningAsOf(e.target.value)} />
            </Field>
          </>
        )}
        {editing && (
          <label className="flex items-center gap-2 text-sm text-content">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active
          </label>
        )}
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-content-muted">{label}</span>
      {children}
    </label>
  );
}
