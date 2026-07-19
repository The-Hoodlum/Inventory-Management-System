// Cash handover register — branch cash handed to a named person / custody account. A
// handover is NOT a "reset the till": it posts an OUT from the branch cash account on
// record (money in transit), and the IN to the receiving account only once the receiver
// CONFIRMS the amount they counted. A short count records a discrepancy with a mandatory
// reason — never silently absorbed. Record/confirm need finance.handover; view finance.read.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HandCoins, Plus, Printer } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { type Column, type DataTableState, ListPage, initialTableState } from "@/components/ds";
import { Button, StatusBadge } from "@/components/ui";
import { ApiError, BASE_URL, tokenStore } from "@/lib/api";
import { type FinanceAccount, type Handover, type HandoverInput, financeApi } from "@/lib/finance";
import { formatDate, formatMoney } from "@/lib/format";
import { useBranches } from "@/lib/refdata";

const INPUT =
  "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const money = (v: string | number) => formatMoney(Number(v), "ZMW");
const STATUS_LABEL: Record<string, string> = {
  PENDING_CONFIRMATION: "Pending", CONFIRMED: "Confirmed", DISPUTED: "Disputed",
};
// Maps to a StatusBadge tone key (which is also the text it renders).
const STATUS_BADGE: Record<string, string> = {
  PENDING_CONFIRMATION: "pending", CONFIRMED: "confirmed", DISPUTED: "disputed",
};

async function openSlip(id: string) {
  const res = await fetch(`${BASE_URL}${financeApi.slipUrl(id)}`, {
    headers: { Authorization: `Bearer ${tokenStore.getAccess() ?? ""}` },
  });
  if (!res.ok) return;
  window.open(URL.createObjectURL(await res.blob()), "_blank");
}

export default function FinanceHandoversPage() {
  const { hasPermission } = useAuth();
  const canHandover = hasPermission("finance.handover");
  const [table, setTable] = useState<DataTableState>(initialTableState(50));
  const [statusFilter, setStatusFilter] = useState("");
  const [modal, setModal] = useState<{ item?: Handover } | null>(null);

  const { data, isFetching } = useQuery({
    queryKey: ["finance-handovers", statusFilter],
    queryFn: () => financeApi.listHandovers(statusFilter ? { status: statusFilter } : {}),
  });

  const rows = useMemo(() => {
    const all = data ?? [];
    const q = table.search.trim().toLowerCase();
    if (!q) return all;
    return all.filter((x) =>
      x.received_by_name.toLowerCase().includes(q) ||
      (x.handed_over_by_name ?? "").toLowerCase().includes(q) ||
      (x.branch_name ?? "").toLowerCase().includes(q));
  }, [data, table.search]);

  const columns: Column<Handover>[] = [
    { key: "when", header: "Date / time", accessor: (x) => x.handover_datetime, render: (x) => formatDate(x.handover_datetime) },
    { key: "branch", header: "Branch", accessor: (x) => x.branch_name ?? "—" },
    { key: "amount", header: "Amount", align: "right", accessor: (x) => Number(x.amount), render: (x) => <span className="font-mono font-medium">{money(x.amount)}</span> },
    { key: "handed", header: "Handed over by", accessor: (x) => x.handed_over_by_name ?? "—" },
    { key: "received", header: "Received by", accessor: (x) => x.received_by_name, render: (x) => <b>{x.received_by_name}</b> },
    {
      key: "discrepancy", header: "Discrepancy", align: "right", defaultHidden: true,
      accessor: (x) => Number(x.discrepancy_amount ?? 0),
      render: (x) => (x.discrepancy_amount && Number(x.discrepancy_amount) !== 0
        ? <span className="font-mono text-red-600">{money(x.discrepancy_amount)}</span> : <span className="text-subtle">—</span>),
    },
    { key: "status", header: "Status", accessor: (x) => STATUS_LABEL[x.status], render: (x) => <StatusBadge status={STATUS_BADGE[x.status]} /> },
    {
      key: "actions", header: "", align: "right",
      render: (x) => (
        <div className="flex justify-end gap-1">
          <button title="Print slip" onClick={() => openSlip(x.id)} className="rounded p-1 text-muted hover:text-brand-600"><Printer className="h-4 w-4" /></button>
          <Button variant="ghost" onClick={() => setModal({ item: x })}>Open</Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <ListPage<Handover>
        title="Cash Handover Register"
        description="Branch cash handed to a named person or custody account. Recording posts the money OUT of the branch (in transit); it's credited to the destination only when the receiver confirms what they counted."
        icon={<HandCoins className="h-5 w-5" />}
        actions={
          <div className="flex items-center gap-2">
            <select className={INPUT} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="PENDING_CONFIRMATION">Pending</option>
              <option value="CONFIRMED">Confirmed</option>
              <option value="DISPUTED">Disputed</option>
            </select>
            {canHandover && <Button onClick={() => setModal({})}><Plus className="h-4 w-4" /> Record handover</Button>}
          </div>
        }
        table={{
          columns, rows, total: rows.length, rowId: (x) => x.id, state: table, onStateChange: setTable,
          loading: isFetching && !data, storageKey: "finance-handovers-table", exportName: "cash-handovers",
          emptyTitle: "No handovers yet",
          emptyHint: canHandover ? "Record a cash handover when a branch hands its takings to the accountant or bank." : undefined,
        }}
      />
      {modal && (modal.item
        ? <HandoverDetail item={modal.item} onClose={() => setModal(null)} canHandover={canHandover} />
        : <RecordHandover onClose={() => setModal(null)} />)}
    </>
  );
}

function RecordHandover({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const branches = useBranches();
  const allowed = user?.accessible_branch_ids ?? [];
  const branchOptions = allowed.length ? branches.list.filter((b) => allowed.includes(b.id)) : branches.list;

  const [branchId, setBranchId] = useState("");
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [amount, setAmount] = useState("");
  const [handedBy, setHandedBy] = useState(user?.full_name ?? "");
  const [receivedBy, setReceivedBy] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const accountsQ = useQuery({
    queryKey: ["finance-accounts", branchId, "handover"],
    queryFn: () => financeApi.listAccounts({ ...(branchId ? { branch_id: branchId } : {}), active_only: true }),
  });
  const cashAccounts = (accountsQ.data ?? []).filter((a: FinanceAccount) => a.type === "CASH");
  const destAccounts = (accountsQ.data ?? []).filter((a: FinanceAccount) => a.id !== fromId);

  const save = useMutation({
    mutationFn: () => {
      const body: HandoverInput = {
        from_account_id: fromId, to_account_id: toId, branch_id: branchId || null,
        amount, handed_over_by_name: handedBy.trim() || null, received_by_name: receivedBy.trim(),
        reference_no: reference.trim() || null, notes: notes.trim() || null,
      };
      return financeApi.createHandover(body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["finance-handovers"] });
      void qc.invalidateQueries({ queryKey: ["finance-accounts"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not record the handover."),
  });

  const canSave = fromId && toId && Number(amount) > 0 && receivedBy.trim() && !save.isPending;

  return (
    <Modal title="Record cash handover" size="md" onClose={onClose}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button disabled={!canSave} onClick={() => { setErr(null); save.mutate(); }}>
            {save.isPending ? "Recording…" : "Record handover"}
          </Button>
        </div>
      }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          This posts the amount OUT of the branch cash account now — the money is in transit until
          the receiver confirms. It is not counted in both places.
        </p>
        <Field label="Branch">
          <select className={INPUT} value={branchId} onChange={(e) => { setBranchId(e.target.value); setFromId(""); setToId(""); }}>
            <option value="">Account's branch</option>
            {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From (branch cash) *">
            <select className={INPUT} value={fromId} onChange={(e) => setFromId(e.target.value)}>
              <option value="">Select…</option>
              {cashAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="To (custody / bank) *">
            <select className={INPUT} value={toId} onChange={(e) => setToId(e.target.value)}>
              <option value="">Select…</option>
              {destAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Amount (ZMW) *"><input className={INPUT} type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Handed over by"><input className={INPUT} value={handedBy} onChange={(e) => setHandedBy(e.target.value)} /></Field>
          <Field label="Received by (name) *"><input className={INPUT} value={receivedBy} onChange={(e) => setReceivedBy(e.target.value)} placeholder="e.g. Grace (accountant)" /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Reference no."><input className={INPUT} value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
          <Field label="Notes"><input className={INPUT} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  );
}

function HandoverDetail({ item, onClose, canHandover }: { item: Handover; onClose: () => void; canHandover: boolean }) {
  const qc = useQueryClient();
  const [counted, setCounted] = useState(item.amount);
  const [reason, setReason] = useState("");
  const [reverseReason, setReverseReason] = useState("");
  const [mode, setMode] = useState<"view" | "reverse">("view");
  const [err, setErr] = useState<string | null>(null);
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["finance-handovers"] });
    void qc.invalidateQueries({ queryKey: ["finance-accounts"] });
    onClose();
  };
  const mismatch = Number(counted) !== Number(item.amount);

  const confirm = useMutation({
    mutationFn: () => financeApi.confirmHandover(item.id, counted, mismatch ? reason.trim() : undefined),
    onSuccess: done,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not confirm."),
  });
  const reverse = useMutation({
    mutationFn: () => financeApi.reverseHandover(item.id, reverseReason.trim()),
    onSuccess: done,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not reverse."),
  });

  const pending = item.status === "PENDING_CONFIRMATION";
  const reversed = !!item.reversed_at;

  return (
    <Modal title="Cash handover" size="md" onClose={onClose}
      footer={
        <div className="flex w-full items-center justify-between">
          <div>
            {canHandover && !reversed && (
              <Button variant="ghost" className="text-red-600 hover:bg-red-50" onClick={() => setMode((m) => (m === "reverse" ? "view" : "reverse"))}>Reverse</Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => openSlip(item.id)}><Printer className="h-4 w-4" /> Slip</Button>
            <Button variant="secondary" onClick={onClose}>Close</Button>
          </div>
        </div>
      }>
      <div className="space-y-3 text-sm">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{err}</div>}
        <div className="grid grid-cols-2 gap-y-2">
          <Detail label="Amount handed over" value={money(item.amount)} strong />
          <Detail label="Status" value={STATUS_LABEL[item.status]} />
          <Detail label="From" value={item.from_account_name ?? "—"} />
          <Detail label="To" value={item.to_account_name ?? "—"} />
          <Detail label="Handed over by" value={item.handed_over_by_name ?? "—"} />
          <Detail label="Received by" value={item.received_by_name} />
          {item.confirmed_amount != null && <Detail label="Counted" value={money(item.confirmed_amount)} />}
          {item.discrepancy_amount != null && Number(item.discrepancy_amount) !== 0 && (
            <Detail label="Discrepancy" value={`${money(item.discrepancy_amount)} — ${item.discrepancy_reason ?? ""}`} tone="red" />
          )}
        </div>
        {reversed && <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">Reversed: {item.reverse_reason}</div>}

        {pending && canHandover && mode === "view" && (
          <div className="space-y-2 rounded-lg border border-line bg-canvas p-3">
            <p className="text-xs font-medium text-content">Confirm receipt</p>
            <Field label="Amount actually counted">
              <input className={INPUT} type="number" min="0" step="0.01" value={counted} onChange={(e) => setCounted(e.target.value)} />
            </Field>
            {mismatch && (
              <Field label="Discrepancy reason (required)">
                <input className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why does the count differ?" />
              </Field>
            )}
            <Button disabled={confirm.isPending || (mismatch && !reason.trim())} onClick={() => { setErr(null); confirm.mutate(); }}>
              {confirm.isPending ? "Confirming…" : mismatch ? "Confirm with discrepancy" : "Confirm receipt"}
            </Button>
          </div>
        )}
        {mode === "reverse" && !reversed && (
          <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-xs text-red-700">Reversing posts the reversing entries (returns the branch cash / undoes the credit). The record is kept.</p>
            <input className={INPUT} placeholder="Reason for reversing" value={reverseReason} onChange={(e) => setReverseReason(e.target.value)} />
            <Button variant="secondary" disabled={!reverseReason.trim() || reverse.isPending} onClick={() => { setErr(null); reverse.mutate(); }}>
              {reverse.isPending ? "Reversing…" : "Confirm reverse"}
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}

function Detail({ label, value, strong, tone }: { label: string; value: string; strong?: boolean; tone?: "red" }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={`${strong ? "font-mono font-semibold text-content" : tone === "red" ? "text-red-600" : "text-content"}`}>{value}</div>
    </div>
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
