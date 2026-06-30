import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Button, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatDate, formatQty, titleCase } from "@/lib/format";
import { type LineReceiptInput, orderRequestsApi } from "@/lib/orderRequests";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const CANCELLABLE = ["draft", "pending", "approved", "partially_approved"];
const ISSUABLE = ["approved", "partially_approved", "partially_issued"];
const RECEIVING = ["issued", "in_transit", "partially_issued", "partially_received"];

type Receipt = { received: string; missing: string; damaged: string; extra: string };
const EMPTY_RECEIPT: Receipt = { received: "", missing: "", damaged: "", extra: "" };

const num = (v: string) => (v.trim() === "" ? 0 : Number(v));

function fmtOpt(v: number | null): string {
  return v === null || v === undefined ? "—" : formatQty(v);
}

export function OrderRequestDetailModal({
  requestId,
  canApprove,
  canIssue,
  canReceive,
  canComplete,
  onClose,
}: {
  requestId: string;
  canApprove: boolean;
  canIssue: boolean;
  canReceive: boolean;
  canComplete: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [approvals, setApprovals] = useState<Record<string, string>>({});
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");
  const [showReceive, setShowReceive] = useState(false);
  const [remarks, setRemarks] = useState("");
  const [receipts, setReceipts] = useState<Record<string, Receipt>>({});
  const [err, setErr] = useState<string | null>(null);

  const { data: req, isLoading } = useQuery({
    queryKey: ["order-requests", requestId],
    queryFn: () => orderRequestsApi.get(requestId),
  });
  const { data: audit } = useQuery({
    queryKey: ["order-requests", requestId, "audit"],
    queryFn: () => orderRequestsApi.audit(requestId),
  });

  // Seed the per-line approval inputs (default = requested) once the request loads.
  useEffect(() => {
    if (req && req.status === "pending") {
      setApprovals(Object.fromEntries(req.lines.map((l) => [l.id, String(l.requested_qty)])));
    }
  }, [req]);

  // Seed the receipt inputs (default received = issued, balanced) on entering the grid.
  useEffect(() => {
    if (req && showReceive) {
      setReceipts(
        Object.fromEntries(
          req.lines.map((l) => [
            l.id,
            {
              received: String(l.issued_qty),
              missing: "",
              damaged: "",
              extra: "",
            },
          ]),
        ),
      );
    }
  }, [showReceive, req]);

  const refresh = () => void qc.invalidateQueries({ queryKey: ["order-requests"] });
  const onErr = (e: unknown) =>
    setErr(e instanceof ApiError ? e.message : "Action failed. Please try again.");
  const done = () => { refresh(); onClose(); };
  const reload = () => { refresh(); void qc.invalidateQueries({ queryKey: ["order-requests", requestId] }); };

  const approve = useMutation({
    mutationFn: () =>
      orderRequestsApi.approve(
        requestId,
        (req?.lines ?? []).map((l) => ({ line_id: l.id, approved_qty: Number(approvals[l.id] ?? 0) })),
      ),
    onSuccess: done, onError: onErr,
  });
  const reject = useMutation({
    mutationFn: () => orderRequestsApi.reject(requestId, reason.trim()),
    onSuccess: done, onError: onErr,
  });
  const issue = useMutation({
    mutationFn: () => orderRequestsApi.issue(requestId),
    onSuccess: done, onError: onErr,
  });
  const cancel = useMutation({
    mutationFn: () => orderRequestsApi.cancel(requestId),
    onSuccess: done, onError: onErr,
  });

  const receiptLines = (): LineReceiptInput[] =>
    (req?.lines ?? []).map((l) => {
      const r = receipts[l.id] ?? EMPTY_RECEIPT;
      return {
        line_id: l.id,
        received_qty: num(r.received),
        missing_qty: num(r.missing),
        damaged_qty: num(r.damaged),
        extra_qty: num(r.extra),
      };
    });

  const receive = useMutation({
    mutationFn: () => orderRequestsApi.receive(requestId, remarks.trim(), receiptLines()),
    onSuccess: () => { reload(); setShowReceive(false); }, onError: onErr,
  });
  const complete = useMutation({
    mutationFn: () => orderRequestsApi.complete(requestId, remarks.trim(), receiptLines()),
    onSuccess: done, onError: onErr,
  });

  const busy =
    approve.isPending || reject.isPending || issue.isPending ||
    cancel.isPending || receive.isPending || complete.isPending;
  const status = req?.status ?? "";
  const isPending = status === "pending";
  const isIssuable = ISSUABLE.includes(status);
  const canOpenReceive = RECEIVING.includes(status) && (canReceive || canComplete);
  const mayCancel = !!req && CANCELLABLE.includes(status) && (canApprove || user?.id === req.requested_by);
  const showReceiptCols = showReceive || ["received", "partially_received", "completed"].includes(status);

  // Live per-line variance + balance while editing the receiving grid.
  const lineVar = (l: { id: string; issued_qty: number }): number => {
    const r = receipts[l.id] ?? EMPTY_RECEIPT;
    return (l.issued_qty + num(r.extra)) - (num(r.received) + num(r.missing) + num(r.damaged));
  };
  const variances = useMemo(
    () => (req?.lines ?? []).map((l) => lineVar(l)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [req, receipts],
  );
  const allBalanced = variances.every((v) => Math.abs(v) < 1e-9);
  const totalVariance = variances.reduce((a, b) => a + b, 0);

  const setReceipt = (id: string, k: keyof Receipt, v: string) =>
    setReceipts((m) => ({ ...m, [id]: { ...(m[id] ?? EMPTY_RECEIPT), [k]: v } }));

  return (
    <Modal
      title={req ? `Transfer ${req.request_number}` : "Stock transfer"}
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Close</Button>

          {req && isPending && canApprove && !showReject && (
            <>
              <Button variant="secondary" onClick={() => setShowReject(true)} disabled={busy}>Reject</Button>
              <Button onClick={() => { setErr(null); approve.mutate(); }} disabled={busy}>
                {approve.isPending ? "Approving…" : "Approve & reserve"}
              </Button>
            </>
          )}
          {req && isPending && canApprove && showReject && (
            <Button onClick={() => { setErr(null); reject.mutate(); }} disabled={busy || reason.trim().length === 0}>
              {reject.isPending ? "Rejecting…" : "Confirm reject"}
            </Button>
          )}

          {req && isIssuable && canIssue && (
            <Button onClick={() => { setErr(null); issue.mutate(); }} disabled={busy}>
              {issue.isPending ? "Issuing…" : "Issue stock"}
            </Button>
          )}

          {req && canOpenReceive && !showReceive && (
            <Button onClick={() => { setErr(null); setShowReceive(true); }} disabled={busy}>
              Receive…
            </Button>
          )}
          {req && showReceive && (
            <>
              {canReceive && (
                <Button
                  variant="secondary"
                  onClick={() => { setErr(null); receive.mutate(); }}
                  disabled={busy || !allBalanced}
                >
                  {receive.isPending ? "Saving…" : "Save receipt"}
                </Button>
              )}
              {canComplete && (
                <Button
                  onClick={() => { setErr(null); complete.mutate(); }}
                  disabled={busy || !allBalanced || remarks.trim().length === 0}
                >
                  {complete.isPending ? "Completing…" : "Complete transfer"}
                </Button>
              )}
            </>
          )}

          {req && mayCancel && !showReject && !showReceive && (
            <Button variant="secondary" onClick={() => { setErr(null); cancel.mutate(); }} disabled={busy}>
              {cancel.isPending ? "Cancelling…" : "Cancel"}
            </Button>
          )}
        </>
      }
    >
      {isLoading || !req ? (
        <div className="flex h-32 items-center justify-center"><Spinner label="Loading…" /></div>
      ) : (
        <div className="space-y-4">
          {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <Field label="Status"><StatusBadge status={req.status} /></Field>
            <Field label="Type">{titleCase(req.transfer_type)}</Field>
            <Field label="From">
              {req.source_branch_name ? `${req.source_branch_name} · ` : ""}{req.source_location_name ?? "—"}
            </Field>
            <Field label="To">
              {req.dest_location_name
                ? `${req.dest_branch_name ? `${req.dest_branch_name} · ` : ""}${req.dest_location_name}`
                : "—"}
            </Field>
            <Field label="Requested by">{req.requester_name ?? "—"}</Field>
            <Field label="Requested">{formatDate(req.requested_date)}</Field>
            {req.issued_date && <Field label="Issued">{formatDate(req.issued_date)}</Field>}
            {req.received_date && <Field label="Received">{formatDate(req.received_date)}</Field>}
            {req.receiver_name && <Field label="Received by">{req.receiver_name}</Field>}
            {req.reason && <Field label="Reason">{req.reason}</Field>}
          </div>

          {/* Reconciliation banner while receiving. */}
          {showReceive && (
            <div
              className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm ${
                allBalanced ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"
              }`}
            >
              <span>
                {allBalanced ? (
                  <span className="font-medium">✓ Balanced</span>
                ) : (
                  <>
                    <span className="font-medium">Validation error.</span>{" "}
                    Receipt quantities do not reconcile. Received + Missing + Damaged must equal Issued + Extra.
                  </>
                )}
              </span>
              <span className="font-mono">Variance: {formatQty(totalVariance)}</span>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 font-medium">Item</th>
                  <th className="py-2 text-right font-medium">Req</th>
                  <th className="py-2 text-right font-medium">Appr</th>
                  <th className="py-2 text-right font-medium">Issued</th>
                  {showReceiptCols && <th className="py-2 text-right font-medium">Received</th>}
                  {showReceiptCols && <th className="py-2 text-right font-medium">Missing</th>}
                  {showReceiptCols && <th className="py-2 text-right font-medium">Damaged</th>}
                  {showReceiptCols && <th className="py-2 text-right font-medium">Extra</th>}
                  {showReceive && <th className="py-2 text-right font-medium">Variance</th>}
                  <th className="py-2 text-right font-medium">Outstanding</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {req.lines.map((l) => {
                  const v = showReceive ? lineVar(l) : l.variance;
                  return (
                    <tr key={l.id}>
                      <td className="py-2">
                        <div className="font-medium text-slate-800">{l.name ?? l.product_id}</div>
                        <div className="font-mono text-xs text-slate-400">{l.sku}</div>
                      </td>
                      <td className="py-2 text-right font-mono">{formatQty(l.requested_qty)}</td>
                      <td className="py-2 text-right font-mono">
                        {isPending && canApprove ? (
                          <input
                            type="number" min={0} max={l.requested_qty}
                            value={approvals[l.id] ?? ""}
                            onChange={(e) => setApprovals((a) => ({ ...a, [l.id]: e.target.value }))}
                            className={`${INPUT} w-20 text-right`}
                          />
                        ) : (
                          formatQty(l.approved_qty)
                        )}
                      </td>
                      <td className="py-2 text-right font-mono">{formatQty(l.issued_qty)}</td>
                      {showReceiptCols && (
                        <>
                          <td className="py-2 text-right font-mono">
                            {showReceive ? (
                              <input type="number" min={0} value={receipts[l.id]?.received ?? ""}
                                onChange={(e) => setReceipt(l.id, "received", e.target.value)}
                                className={`${INPUT} w-16 text-right`} />
                            ) : fmtOpt(l.received_qty)}
                          </td>
                          <td className="py-2 text-right font-mono">
                            {showReceive ? (
                              <input type="number" min={0} value={receipts[l.id]?.missing ?? ""}
                                onChange={(e) => setReceipt(l.id, "missing", e.target.value)}
                                className={`${INPUT} w-16 text-right`} />
                            ) : fmtOpt(l.missing_qty)}
                          </td>
                          <td className="py-2 text-right font-mono">
                            {showReceive ? (
                              <input type="number" min={0} value={receipts[l.id]?.damaged ?? ""}
                                onChange={(e) => setReceipt(l.id, "damaged", e.target.value)}
                                className={`${INPUT} w-16 text-right`} />
                            ) : fmtOpt(l.damaged_qty)}
                          </td>
                          <td className="py-2 text-right font-mono">
                            {showReceive ? (
                              <input type="number" min={0} value={receipts[l.id]?.extra ?? ""}
                                onChange={(e) => setReceipt(l.id, "extra", e.target.value)}
                                className={`${INPUT} w-16 text-right`} />
                            ) : fmtOpt(l.extra_qty)}
                          </td>
                        </>
                      )}
                      {showReceive && (
                        <td className={`py-2 text-right font-mono ${Math.abs(v) < 1e-9 ? "text-emerald-600" : "text-red-600"}`}>
                          {formatQty(v)}
                        </td>
                      )}
                      <td className="py-2 text-right font-mono text-slate-500">{formatQty(l.outstanding_qty)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {req.comments && !req.reason && (
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <span className="font-medium text-slate-700">Comments: </span>{req.comments}
            </div>
          )}

          {req.completion_remarks && !showReceive && (
            <div className="rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-800">
              <span className="font-medium">Receipt note: </span>{req.completion_remarks}
            </div>
          )}

          {showReceive && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">
                Receipt remarks {canComplete ? "(required to complete)" : "(optional)"}
              </span>
              <textarea
                value={remarks}
                onChange={(e) => setRemarks(e.target.value)}
                rows={2}
                className={`${INPUT} w-full`}
                placeholder="Who took delivery, and any discrepancies (missing / damaged / extra)."
                autoFocus
              />
            </label>
          )}

          {showReject && isPending && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Rejection reason (required)</span>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                className={`${INPUT} w-full`}
                autoFocus
              />
            </label>
          )}

          {audit && audit.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">History</div>
              <ul className="space-y-1 text-xs text-slate-500">
                {audit.map((a, i) => (
                  <li key={i} className="flex justify-between">
                    <span>{titleCase(a.action)}{a.new_status ? ` → ${titleCase(a.new_status)}` : ""}</span>
                    <span className="text-slate-400">{formatDate(a.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-400">{label}:</span>
      <span className="font-medium text-slate-700">{children}</span>
    </div>
  );
}
