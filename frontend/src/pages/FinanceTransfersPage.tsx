// Account transfers — move money between two finance accounts (e.g. banking cash: Cash in
// hand -> Bank). Posts a PAIRED OUT + IN in one transaction; net across the two accounts is
// unchanged. Reversible only by a reversing pair (never a one-sided edit). Needs
// finance.transfer to create/reverse; finance.read to view.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type FinanceAccount, type Transfer, financeApi } from "@/lib/finance";
import { formatDate, formatMoney } from "@/lib/format";

const INPUT =
  "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const money = (v: string | number) => formatMoney(Number(v), "ZMW");

export default function FinanceTransfersPage() {
  const { hasPermission } = useAuth();
  const canTransfer = hasPermission("finance.transfer");
  const [table, setTable] = useState<DataTableState>(initialTableState(50));
  const [showNew, setShowNew] = useState(false);

  const { data, isFetching } = useQuery({ queryKey: ["finance-transfers"], queryFn: () => financeApi.listTransfers() });
  const rows = useMemo(() => {
    const all = data ?? [];
    const q = table.search.trim().toLowerCase();
    if (!q) return all;
    return all.filter((t) => (t.from_account_name ?? "").toLowerCase().includes(q) || (t.to_account_name ?? "").toLowerCase().includes(q));
  }, [data, table.search]);

  const qc = useQueryClient();
  const reverse = useMutation({
    mutationFn: (t: Transfer) => financeApi.reverseTransfer(t.id, window.prompt("Reason for reversing this transfer?") || ""),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["finance-transfers"] }); void qc.invalidateQueries({ queryKey: ["finance-accounts"] }); },
  });

  const columns: Column<Transfer>[] = [
    { key: "when", header: "Date", accessor: (t) => t.occurred_at, render: (t) => formatDate(t.occurred_at) },
    { key: "from", header: "From", accessor: (t) => t.from_account_name ?? "—" },
    { key: "to", header: "To", accessor: (t) => t.to_account_name ?? "—" },
    { key: "amount", header: "Amount", align: "right", accessor: (t) => Number(t.amount), render: (t) => <span className={`font-mono font-medium ${t.status === "reversed" ? "text-subtle line-through" : "text-content"}`}>{money(t.amount)}</span> },
    { key: "reference", header: "Reference", accessor: (t) => t.reference_no ?? "—", defaultHidden: true },
    { key: "status", header: "Status", accessor: (t) => t.status, render: (t) => <StatusBadge status={t.status === "reversed" ? "cancelled" : "active"} /> },
  ];
  if (canTransfer) {
    columns.push({
      key: "actions", header: "", align: "right",
      render: (t) => t.status === "completed"
        ? <Button variant="ghost" className="text-red-600 hover:bg-red-50" disabled={reverse.isPending} onClick={() => { if (window.confirm("Reverse this transfer?")) reverse.mutate(t); }}>Reverse</Button>
        : null,
    });
  }

  return (
    <>
      <ListPage<Transfer>
        title="Account Transfers"
        description="Move money between accounts (e.g. banking cash). Each transfer posts a paired OUT + IN — the total across accounts never changes. Reversible only by a reversing pair."
        icon={<ArrowLeftRight className="h-5 w-5" />}
        actions={canTransfer ? <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New transfer</Button> : undefined}
        table={{
          columns, rows, total: rows.length, rowId: (t) => t.id, state: table, onStateChange: setTable,
          loading: isFetching && !data, storageKey: "finance-transfers-table", exportName: "account-transfers",
          emptyTitle: "No transfers yet",
        }}
      />
      {showNew && <TransferModal onClose={() => setShowNew(false)} />}
    </>
  );
}

function TransferModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [amount, setAmount] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const accountsQ = useQuery({ queryKey: ["finance-accounts", "all-active"], queryFn: () => financeApi.listAccounts({ active_only: true }) });
  const accounts = accountsQ.data ?? [];

  const save = useMutation({
    mutationFn: () => financeApi.createTransfer({ from_account_id: fromId, to_account_id: toId, amount, reference_no: reference.trim() || null, notes: notes.trim() || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["finance-transfers"] });
      void qc.invalidateQueries({ queryKey: ["finance-accounts"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the transfer."),
  });
  const canSave = fromId && toId && fromId !== toId && Number(amount) > 0 && !save.isPending;

  return (
    <Modal title="New transfer" size="md" onClose={onClose}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button disabled={!canSave} onClick={() => { setErr(null); save.mutate(); }}>{save.isPending ? "Transferring…" : "Transfer"}</Button>
        </div>
      }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="From account *">
            <select className={INPUT} value={fromId} onChange={(e) => setFromId(e.target.value)}>
              <option value="">Select…</option>
              {accounts.map((a: FinanceAccount) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="To account *">
            <select className={INPUT} value={toId} onChange={(e) => setToId(e.target.value)}>
              <option value="">Select…</option>
              {accounts.filter((a: FinanceAccount) => a.id !== fromId).map((a: FinanceAccount) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Amount (ZMW) *"><input className={INPUT} type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Reference no."><input className={INPUT} value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
          <Field label="Notes"><input className={INPUT} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
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
