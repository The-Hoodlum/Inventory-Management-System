// Delivery-note detail — header, mixed lines, and TYPE-driven actions: dispatch (send
// in transit), receive (per-line confirm + discrepancy), cancel (draft only), and a
// printable PDF. Stock moves through the existing paths; this screen only orchestrates.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type DispatchLine, type ReceiveBody, dispatchApi, dispatchStatusLabel } from "@/lib/dispatch";
import { formatDate } from "@/lib/format";

export default function DeliveryNoteDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canDispatch = hasPermission("delivery_note.dispatch");
  const canReceive = hasPermission("delivery_note.receive");
  const [err, setErr] = useState<string | null>(null);
  const [receiving, setReceiving] = useState(false);

  const { data: note, isLoading } = useQuery({ queryKey: ["dispatch", "note", id], queryFn: () => dispatchApi.get(id), enabled: !!id });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["dispatch"] }); };
  const onErr = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Action failed.");

  const dispatch = useMutation({ mutationFn: () => dispatchApi.dispatch(id), onSuccess: refresh, onError: onErr });
  const cancel = useMutation({ mutationFn: () => dispatchApi.cancel(id), onSuccess: refresh, onError: onErr });

  if (isLoading || !note) {
    return (
      <div><PageHeader title="Delivery note" /><div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div></div>
    );
  }

  const canAct = note.status === "draft";
  const canRecv = note.status === "in_transit" || note.status === "partially_received";

  return (
    <div>
      <PageHeader
        title={note.note_number}
        description={`${dispatchStatusLabel(note.dispatch_type)} — documents a stock movement`}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => navigate("/delivery-notes")}>Back</Button>
            <Button variant="secondary" onClick={() => void dispatchApi.downloadPdf(note.id, note.note_number)}>PDF</Button>
            {canAct && canDispatch && (
              <Button disabled={dispatch.isPending} onClick={() => { setErr(null); dispatch.mutate(); }}>
                {dispatch.isPending ? "Dispatching…" : "Dispatch"}
              </Button>
            )}
            {canAct && canDispatch && (
              <Button variant="ghost" disabled={cancel.isPending} onClick={() => { setErr(null); cancel.mutate(); }}>Cancel</Button>
            )}
            {canRecv && canReceive && !receiving && (
              <Button onClick={() => setReceiving(true)}>Receive…</Button>
            )}
          </div>
        }
      />

      {err && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <Card className="mb-4 p-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm md:grid-cols-4">
          <Info label="Status"><StatusBadge status={note.status} /></Info>
          <Info label="From">{note.from_branch_name ?? "—"} · {note.from_warehouse_name ?? "—"}</Info>
          <Info label="To">{note.to_branch_name ?? "—"} · {note.to_warehouse_name ?? "—"}</Info>
          <Info label="Created">{formatDate(note.created_at)}</Info>
          {note.dispatched_at && <Info label="Dispatched">{formatDate(note.dispatched_at)}</Info>}
          {note.received_at && <Info label="Received">{formatDate(note.received_at)}{note.received_by ? ` · ${note.received_by}` : ""}</Info>}
          {note.remarks && <Info label="Remarks">{note.remarks}</Info>}
        </div>
      </Card>

      {receiving && canRecv ? (
        <ReceiveForm note={note} onClose={() => setReceiving(false)} onDone={() => { setReceiving(false); refresh(); }} />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Item / Chassis</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 text-right font-medium">Dispatched</th>
                <th className="px-4 py-2.5 text-right font-medium">Received</th>
                <th className="px-4 py-2.5 text-right font-medium">Short</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {note.lines.map((l) => (
                <tr key={l.id}>
                  <td className="px-4 py-3">{lineTitle(l)}</td>
                  <td className="px-4 py-3 text-slate-500">{l.line_kind === "motorcycle" ? "Motorcycle" : "Spare part"}</td>
                  <td className="px-4 py-3 text-right font-mono">{l.dispatched_qty}</td>
                  <td className="px-4 py-3 text-right font-mono">{note.status === "draft" || note.status === "in_transit" ? "—" : l.received_qty}</td>
                  <td className="px-4 py-3 text-right font-mono">{(l.missing_qty + l.damaged_qty) > 0 ? (l.missing_qty + l.damaged_qty) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function lineTitle(l: DispatchLine) {
  if (l.line_kind === "motorcycle") {
    return (
      <span>
        <span className="font-mono text-[13px] text-slate-800">{l.chassis_number}</span>
        <span className="ml-2 text-xs text-slate-400">{l.model_name}{l.engine_number ? ` · Eng ${l.engine_number}` : ""}</span>
      </span>
    );
  }
  return <span>{l.name}<span className="ml-2 font-mono text-xs text-slate-400">{l.sku}</span></span>;
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div><div className="mt-0.5 text-slate-700">{children}</div></div>;
}

const INPUT = "rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-right focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function ReceiveForm({ note, onClose, onDone }: { note: import("@/lib/dispatch").DispatchNote; onClose: () => void; onDone: () => void }) {
  const [receivedBy, setReceivedBy] = useState("");
  // Default: everything received in full.
  const [parts, setParts] = useState<Record<string, { received: number; damaged: number }>>(
    Object.fromEntries(note.lines.filter((l) => l.line_kind === "part").map((l) => [l.id, { received: l.dispatched_qty, damaged: 0 }])),
  );
  const [bikes, setBikes] = useState<Record<string, boolean>>(
    Object.fromEntries(note.lines.filter((l) => l.line_kind === "motorcycle").map((l) => [l.id, true])),
  );
  const [err, setErr] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: () => {
      const body: ReceiveBody = {
        received_by: receivedBy || undefined,
        part_lines: Object.entries(parts).map(([line_id, v]) => ({ line_id, received_qty: v.received, damaged_qty: v.damaged || undefined })),
        bike_lines: Object.entries(bikes).map(([line_id, received]) => ({ line_id, received })),
      };
      return dispatchApi.receive(note.id, body);
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not confirm receipt."),
  });

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Confirm receipt</h3>
        <span className="text-xs text-slate-400">Adjust quantities / untick a missing chassis — the shortfall is recorded, never absorbed.</span>
      </div>
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="space-y-2">
        {note.lines.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-3 border-b border-slate-100 py-2 text-sm">
            <span className="min-w-0 flex-1">{lineTitle(l)}</span>
            {l.line_kind === "part" ? (
              <>
                <label className="flex items-center gap-1 text-xs text-slate-500">Received
                  <input type="number" min={0} max={l.dispatched_qty} value={parts[l.id]?.received ?? 0}
                    onChange={(e) => setParts((p) => ({ ...p, [l.id]: { ...p[l.id], received: Math.min(l.dispatched_qty, Math.max(0, Number(e.target.value))) } }))}
                    className={`${INPUT} w-16`} /> / {l.dispatched_qty}</label>
                <label className="flex items-center gap-1 text-xs text-slate-500">Damaged
                  <input type="number" min={0} value={parts[l.id]?.damaged ?? 0}
                    onChange={(e) => setParts((p) => ({ ...p, [l.id]: { ...p[l.id], damaged: Math.max(0, Number(e.target.value)) } }))}
                    className={`${INPUT} w-14`} /></label>
              </>
            ) : (
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={bikes[l.id] ?? false} onChange={(e) => setBikes((b) => ({ ...b, [l.id]: e.target.checked }))} />
                Arrived
              </label>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <input className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm" placeholder="Received by (name)" value={receivedBy} onChange={(e) => setReceivedBy(e.target.value)} />
        <Button disabled={m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Confirming…" : "Confirm receipt"}</Button>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
      </div>
    </Card>
  );
}
