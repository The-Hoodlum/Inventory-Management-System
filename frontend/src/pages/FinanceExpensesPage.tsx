// Finance expenses — money out. Recording one posts an OUT movement to the chosen account
// (its balance drops immediately). MANAGER-ONLY create/edit/void (finance.expense.manage);
// anyone with finance.read may VIEW within their branch scope. Corrections are voids
// (reversals), never deletes. Categories are a configurable tenant list. Optional receipt.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Paperclip, Plus, Tags, Wallet } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError, BASE_URL, tokenStore } from "@/lib/api";
import {
  type Expense,
  type ExpenseInput,
  type FinanceAccount,
  financeApi,
} from "@/lib/finance";
import { formatDate, formatMoney } from "@/lib/format";
import { useBranches } from "@/lib/refdata";

const INPUT =
  "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const money = (v: string | number) => formatMoney(Number(v), "ZMW");

async function openReceipt(id: string) {
  const res = await fetch(`${BASE_URL}${financeApi.receiptUrl(id)}`, {
    headers: { Authorization: `Bearer ${tokenStore.getAccess() ?? ""}` },
  });
  if (!res.ok) return;
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank");
}

export default function FinanceExpensesPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("finance.expense.manage");
  const [table, setTable] = useState<DataTableState>(initialTableState(50));
  const [modal, setModal] = useState<{ item?: Expense } | null>(null);
  const [catModal, setCatModal] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("");

  const { data, isFetching } = useQuery({
    queryKey: ["finance-expenses", categoryFilter],
    queryFn: () => financeApi.listExpenses(categoryFilter ? { category_id: categoryFilter } : {}),
  });
  const categoriesQ = useQuery({ queryKey: ["finance-categories"], queryFn: () => financeApi.listCategories() });

  const rows = useMemo(() => {
    const all = data ?? [];
    const q = table.search.trim().toLowerCase();
    if (!q) return all;
    return all.filter((e) =>
      (e.payee ?? "").toLowerCase().includes(q) ||
      (e.description ?? "").toLowerCase().includes(q) ||
      (e.category_name ?? "").toLowerCase().includes(q) ||
      (e.account_name ?? "").toLowerCase().includes(q));
  }, [data, table.search]);

  const columns: Column<Expense>[] = [
    { key: "date", header: "Date", accessor: (e) => e.expense_date, render: (e) => formatDate(e.expense_date) },
    { key: "category", header: "Category", accessor: (e) => e.category_name ?? "—" },
    { key: "payee", header: "Payee", accessor: (e) => e.payee ?? "—" },
    { key: "account", header: "Account", accessor: (e) => e.account_name ?? "—" },
    { key: "branch", header: "Branch", accessor: (e) => e.branch_name ?? "—", defaultHidden: true },
    {
      key: "amount", header: "Amount", align: "right", accessor: (e) => Number(e.amount),
      render: (e) => (
        <span className={`font-mono font-medium ${e.status === "voided" ? "text-subtle line-through" : "text-content"}`}>
          {money(e.amount)}
        </span>
      ),
    },
    {
      key: "receipt", header: "", align: "center",
      render: (e) => e.has_attachment
        ? <button title="View receipt" onClick={() => openReceipt(e.id)} className="text-brand-600 hover:text-brand-700"><Paperclip className="h-4 w-4" /></button>
        : null,
    },
    {
      key: "status", header: "Status", accessor: (e) => e.status,
      render: (e) => <StatusBadge status={e.status === "voided" ? "cancelled" : "active"} />,
    },
  ];
  if (canManage) {
    columns.push({
      key: "actions", header: "", align: "right",
      render: (e) => <Button variant="ghost" onClick={() => setModal({ item: e })}>Open</Button>,
    });
  }

  return (
    <>
      <ListPage<Expense>
        title="Expenses"
        description="Money out. Recording an expense posts it against an account, so cash in hand drops immediately. Corrections are voids, never deletes."
        icon={<Wallet className="h-5 w-5" />}
        actions={
          <div className="flex items-center gap-2">
            <select className={INPUT} value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="">All categories</option>
              {(categoriesQ.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            {canManage && (
              <>
                <Button variant="secondary" onClick={() => setCatModal(true)}><Tags className="h-4 w-4" /> Categories</Button>
                <Button onClick={() => setModal({})}><Plus className="h-4 w-4" /> Record expense</Button>
              </>
            )}
          </div>
        }
        table={{
          columns, rows, total: rows.length, rowId: (e) => e.id, state: table, onStateChange: setTable,
          loading: isFetching && !data, storageKey: "finance-expenses-table", exportName: "expenses",
          emptyTitle: "No expenses yet",
          emptyHint: canManage ? "Record your first expense to start tracking money out." : undefined,
        }}
      />
      {modal && <ExpenseModal item={modal.item} onClose={() => setModal(null)} canManage={canManage} />}
      {catModal && <CategoriesModal onClose={() => setCatModal(false)} />}
    </>
  );
}

function ExpenseModal({ item, onClose, canManage }: { item?: Expense; onClose: () => void; canManage: boolean }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const branches = useBranches();
  const allowed = user?.accessible_branch_ids ?? [];
  const branchOptions = allowed.length ? branches.list.filter((b) => allowed.includes(b.id)) : branches.list;
  const editing = !!item;

  const [branchId, setBranchId] = useState(item?.branch_id ?? "");
  const [accountId, setAccountId] = useState(item?.account_id ?? "");
  const [amount, setAmount] = useState(item?.amount ?? "");
  const [date, setDate] = useState(item?.expense_date ?? new Date().toISOString().slice(0, 10));
  const [categoryId, setCategoryId] = useState(item?.category_id ?? "");
  const [payee, setPayee] = useState(item?.payee ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [reference, setReference] = useState(item?.reference_no ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [voiding, setVoiding] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const accountsQ = useQuery({
    queryKey: ["finance-accounts", branchId],
    queryFn: () => financeApi.listAccounts(branchId ? { branch_id: branchId, active_only: true } : { active_only: true }),
    enabled: !editing,
  });
  const categoriesQ = useQuery({ queryKey: ["finance-categories", "active"], queryFn: () => financeApi.listCategories(true) });

  const done = () => {
    void qc.invalidateQueries({ queryKey: ["finance-expenses"] });
    void qc.invalidateQueries({ queryKey: ["finance-accounts"] });
    onClose();
  };

  const save = useMutation({
    mutationFn: async () => {
      if (editing) {
        await financeApi.updateExpense(item!.id, {
          category_id: categoryId || null, payee: payee.trim() || null,
          description: description.trim() || null, reference_no: reference.trim() || null, expense_date: date,
        });
        if (file) await financeApi.uploadReceipt(item!.id, file);
        return;
      }
      const body: ExpenseInput = {
        account_id: accountId, branch_id: branchId || null, amount, expense_date: date,
        category_id: categoryId || null, payee: payee.trim() || null,
        description: description.trim() || null, reference_no: reference.trim() || null,
      };
      const created = await financeApi.createExpense(body);
      if (file) await financeApi.uploadReceipt(created.id, file);
    },
    onSuccess: done,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the expense."),
  });

  const doVoid = useMutation({
    mutationFn: () => financeApi.voidExpense(item!.id, voidReason.trim()),
    onSuccess: done,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not void the expense."),
  });

  const voided = item?.status === "voided";
  const canSave = !save.isPending && (editing || (accountId && Number(amount) > 0));

  return (
    <Modal
      title={editing ? "Expense" : "Record expense"}
      size="md"
      onClose={onClose}
      footer={
        <div className="flex w-full items-center justify-between">
          <div>
            {editing && canManage && !voided && (
              <Button variant="ghost" className="text-red-600 hover:bg-red-50" onClick={() => setVoiding((v) => !v)}>
                Void
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>Close</Button>
            {canManage && !voided && (
              <Button disabled={!canSave} onClick={() => { setErr(null); save.mutate(); }}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        {voided && (
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
            Voided{item?.void_reason ? `: ${item.void_reason}` : ""}. The reversing entry has restored the balance.
          </div>
        )}
        {voiding && !voided && (
          <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-xs text-red-700">Voiding reverses the money-out (restores the balance). The record is kept. Reason is required.</p>
            <input className={INPUT} placeholder="Reason for voiding" value={voidReason} onChange={(e) => setVoidReason(e.target.value)} />
            <Button variant="secondary" disabled={!voidReason.trim() || doVoid.isPending} onClick={() => { setErr(null); doVoid.mutate(); }}>
              {doVoid.isPending ? "Voiding…" : "Confirm void"}
            </Button>
          </div>
        )}

        {!editing && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Branch">
              <select className={INPUT} value={branchId} onChange={(e) => { setBranchId(e.target.value); setAccountId(""); }}>
                <option value="">Account's branch</option>
                {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </Field>
            <Field label="Paid from account *">
              <select className={INPUT} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">Select…</option>
                {(accountsQ.data ?? []).map((a: FinanceAccount) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </Field>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount (ZMW) *">
            <input className={INPUT} type="number" min="0" step="0.01" value={amount}
              disabled={editing} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Date *">
            <input className={INPUT} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
        </div>
        <Field label="Category">
          <select className={INPUT} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">Uncategorised</option>
            {(categoriesQ.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Payee"><input className={INPUT} value={payee} onChange={(e) => setPayee(e.target.value)} placeholder="Who was paid" /></Field>
        <Field label="Description"><input className={INPUT} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Reference no."><input className={INPUT} value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
          {canManage && !voided && (
            <Field label="Receipt (image/PDF)">
              <input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-xs text-muted file:mr-2 file:rounded-md file:border-0 file:bg-slate-100 file:px-2 file:py-1 file:text-xs" />
            </Field>
          )}
        </div>
        {editing && item?.has_attachment && (
          <button onClick={() => openReceipt(item.id)} className="text-sm text-brand-600 hover:underline">
            <Paperclip className="mr-1 inline h-3.5 w-3.5" />View current receipt
          </button>
        )}
      </div>
    </Modal>
  );
}

function CategoriesModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["finance-categories"], queryFn: () => financeApi.listCategories() });
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["finance-categories"] });

  const add = useMutation({
    mutationFn: () => financeApi.createCategory(name.trim()),
    onSuccess: () => { setName(""); void refresh(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not add the category."),
  });
  const toggle = useMutation({
    mutationFn: (c: { id: string; is_active: boolean }) => financeApi.updateCategory(c.id, { is_active: !c.is_active }),
    onSuccess: () => void refresh(),
  });

  return (
    <Modal title="Expense categories" size="sm" onClose={onClose}
      footer={<div className="flex w-full justify-end"><Button variant="secondary" onClick={onClose}>Done</Button></div>}>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="flex gap-2">
          <input className={INPUT} placeholder="New category (e.g. Fuel)" value={name} onChange={(e) => setName(e.target.value)} />
          <Button disabled={!name.trim() || add.isPending} onClick={() => { setErr(null); add.mutate(); }}>Add</Button>
        </div>
        <div className="divide-y divide-line">
          {(data ?? []).map((c) => (
            <div key={c.id} className="flex items-center justify-between py-2 text-sm">
              <span className={c.is_active ? "text-content" : "text-subtle line-through"}>{c.name}</span>
              <button className="text-xs text-brand-600 hover:underline" onClick={() => toggle.mutate(c)}>
                {c.is_active ? "Deactivate" : "Reactivate"}
              </button>
            </div>
          ))}
          {(data ?? []).length === 0 && <p className="py-3 text-center text-xs text-subtle">No categories yet.</p>}
        </div>
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
