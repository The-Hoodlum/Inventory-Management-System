import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Modal } from "@/components/Modal";
import { Button, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatDate, formatQty, titleCase } from "@/lib/format";
import { orderRequestsApi } from "@/lib/orderRequests";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export function OrderRequestDetailModal({
  requestId,
  canApprove,
  canIssue,
  onClose,
}: {
  requestId: string;
  canApprove: boolean;
  canIssue: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [approvals, setApprovals] = useState<Record<string, string>>({});
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");
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

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["order-requests"] });
  };
  const onErr = (e: unknown) =>
    setErr(e instanceof ApiError ? e.message : "Action failed. Please try again.");

  const approve = useMutation({
    mutationFn: () =>
      orderRequestsApi.approve(
        requestId,
        (req?.lines ?? []).map((l) => ({ line_id: l.id, approved_qty: Number(approvals[l.id] ?? 0) }))
      ),
    onSuccess: () => { refresh(); onClose(); },
    onError: onErr,
  });
  const reject = useMutation({
    mutationFn: () => orderRequestsApi.reject(requestId, reason.trim()),
    onSuccess: () => { refresh(); onClose(); },
    onError: onErr,
  });
  const issue = useMutation({
    mutationFn: () => orderRequestsApi.issue(requestId),
    onSuccess: () => { refresh(); onClose(); },
    onError: onErr,
  });

  const busy = approve.isPending || reject.isPending || issue.isPending;
  const isPending = req?.status === "pending";
  const isApproved = req?.status === "approved" || req?.status === "partially_approved";

  return (
    <Modal
      title={req ? `Request ${req.request_number}` : "Order request"}
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Close</Button>
          {req && isPending && canApprove && !showReject && (
            <>
              <Button variant="secondary" onClick={() => setShowReject(true)} disabled={busy}>
                Reject
              </Button>
              <Button onClick={() => { setErr(null); approve.mutate(); }} disabled={busy}>
                {approve.isPending ? "Approving…" : "Approve"}
              </Button>
            </>
          )}
          {req && isPending && canApprove && showReject && (
            <Button
              onClick={() => { setErr(null); reject.mutate(); }}
              disabled={busy || reason.trim().length === 0}
            >
              {reject.isPending ? "Rejecting…" : "Confirm reject"}
            </Button>
          )}
          {req && isApproved && canIssue && (
            <Button onClick={() => { setErr(null); issue.mutate(); }} disabled={busy}>
              {issue.isPending ? "Issuing…" : "Issue stock"}
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
            <Field label="Purpose">{titleCase(req.purpose)}</Field>
            <Field label="Branch">{req.branch_name ?? "—"}</Field>
            <Field label="Requested by">{req.requester_name ?? "—"}</Field>
            <Field label="Requested">{formatDate(req.requested_date)}</Field>
            {req.issued_date && <Field label="Issued">{formatDate(req.issued_date)}</Field>}
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="py-2 font-medium">Item</th>
                <th className="py-2 text-right font-medium">Requested</th>
                <th className="py-2 text-right font-medium">Approved</th>
                <th className="py-2 text-right font-medium">Issued</th>
                <th className="py-2 text-right font-medium">Outstanding</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {req.lines.map((l) => (
                <tr key={l.id}>
                  <td className="py-2">
                    <div className="font-medium text-slate-800">{l.name ?? l.product_id}</div>
                    <div className="font-mono text-xs text-slate-400">{l.sku}</div>
                  </td>
                  <td className="py-2 text-right font-mono">{formatQty(l.requested_qty)}</td>
                  <td className="py-2 text-right font-mono">
                    {isPending && canApprove ? (
                      <input
                        type="number"
                        min={0}
                        max={l.requested_qty}
                        value={approvals[l.id] ?? ""}
                        onChange={(e) =>
                          setApprovals((a) => ({ ...a, [l.id]: e.target.value }))
                        }
                        className={`${INPUT} w-20 text-right`}
                      />
                    ) : (
                      formatQty(l.approved_qty)
                    )}
                  </td>
                  <td className="py-2 text-right font-mono">{formatQty(l.issued_qty)}</td>
                  <td className="py-2 text-right font-mono text-slate-500">{formatQty(l.outstanding_qty)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {req.comments && (
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <span className="font-medium text-slate-700">Comments: </span>{req.comments}
            </div>
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
