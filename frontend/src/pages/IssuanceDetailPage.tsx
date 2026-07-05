// Issuance detail — header, lines, and actions: issue (send out on loan), return
// (per-bike condition + per-item qty; damaged → on_hold), cancel (draft only), PDF.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { type Condition, type Issuance, type IssuanceLine, type ReturnIssuanceBody, issuanceApi, issuanceStatusLabel } from "@/lib/issuance";

const CONDITIONS: { value: Condition; label: string }[] = [
  { value: "good", label: "Good" },
  { value: "fair", label: "Fair" },
  { value: "needs_attention", label: "Needs attention (→ hold)" },
];

export default function IssuanceDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canIssue = hasPermission("delivery_note.dispatch");
  const canReturn = hasPermission("delivery_note.receive");
  const [err, setErr] = useState<string | null>(null);
  const [returning, setReturning] = useState(false);

  const { data: iss, isLoading } = useQuery({ queryKey: ["issuance", "one", id], queryFn: () => issuanceApi.get(id), enabled: !!id });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["issuance"] }); };
  const onErr = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Action failed.");
  const issue = useMutation({ mutationFn: () => issuanceApi.issue(id), onSuccess: refresh, onError: onErr });
  const cancel = useMutation({ mutationFn: () => issuanceApi.cancel(id), onSuccess: refresh, onError: onErr });

  if (isLoading || !iss) return <div><PageHeader title="Issuance" /><div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div></div>;

  const isDraft = iss.status === "draft";
  const isOut = iss.status === "out_on_loan" || iss.status === "partially_returned";

  return (
    <div>
      <PageHeader
        title={iss.issuance_number}
        description="Out-and-back loan — on-loan stock is not sellable but never deducted."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => navigate("/issuances")}>Back</Button>
            <Button variant="secondary" onClick={() => void issuanceApi.downloadPdf(iss.id, iss.issuance_number)}>PDF</Button>
            {isDraft && canIssue && <Button disabled={issue.isPending} onClick={() => { setErr(null); issue.mutate(); }}>{issue.isPending ? "Issuing…" : "Issue (out on loan)"}</Button>}
            {isDraft && canIssue && <Button variant="ghost" disabled={cancel.isPending} onClick={() => { setErr(null); cancel.mutate(); }}>Cancel</Button>}
            {isOut && canReturn && !returning && <Button onClick={() => setReturning(true)}>Record return…</Button>}
          </div>
        }
      />
      {err && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <Card className="mb-4 p-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm md:grid-cols-4">
          <Info label="Status"><StatusBadge status={iss.status} /></Info>
          <Info label="Requestor">{iss.requestor ?? "—"}</Info>
          <Info label="Department">{iss.department ?? "—"}</Info>
          <Info label="Purpose">{iss.purpose ?? "—"}</Info>
          <Info label="Source">{iss.warehouse_name ?? "—"}</Info>
          <Info label="Issued">{iss.issued_at ? formatDate(iss.issued_at) : "—"}</Info>
          <Info label="Expected back">{iss.expected_return_date ?? "—"}{iss.overdue ? " (overdue)" : ""}</Info>
          {iss.remarks && <Info label="Remarks">{iss.remarks}</Info>}
        </div>
      </Card>

      {returning && isOut ? (
        <ReturnForm iss={iss} onClose={() => setReturning(false)} onDone={() => { setReturning(false); refresh(); }} />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Item / Chassis</th>
                <th className="px-4 py-2.5 font-medium">Kind</th>
                <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                <th className="px-4 py-2.5 font-medium">Returnable</th>
                <th className="px-4 py-2.5 font-medium">Returned</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {iss.lines.map((l) => (
                <tr key={l.id}>
                  <td className="px-4 py-3">{lineTitle(l)}</td>
                  <td className="px-4 py-3 text-slate-500">{l.line_kind === "motorcycle" ? "Bike" : "Item"}</td>
                  <td className="px-4 py-3 text-right font-mono">{l.qty}</td>
                  <td className="px-4 py-3 text-slate-500">{l.consumable ? "No (consumable)" : "Yes"}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {l.returned_at ? (l.line_kind === "motorcycle" ? issuanceStatusLabel(l.condition ?? "returned") : `${l.returned_qty}${l.missing_qty ? ` (−${l.missing_qty} lost)` : ""}`) : (l.consumable ? "—" : "out")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function lineTitle(l: IssuanceLine) {
  if (l.line_kind === "motorcycle") {
    return <span><span className="font-mono text-[13px] text-slate-800">{l.chassis_number}</span><span className="ml-2 text-xs text-slate-400">{l.model_name}{l.odometer_out != null ? ` · Odo ${l.odometer_out}` : ""}</span></span>;
  }
  return <span>{l.name}<span className="ml-2 font-mono text-xs text-slate-400">{l.sku}</span></span>;
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div><div className="mt-0.5 text-slate-700">{children}</div></div>;
}

const IN = "rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function ReturnForm({ iss, onClose, onDone }: { iss: Issuance; onClose: () => void; onDone: () => void }) {
  // Only lines still out (returnable, not consumable, not yet returned) can be returned.
  const openLines = iss.lines.filter((l) => l.returnable && !l.consumable && !l.returned_at);
  const [parts, setParts] = useState<Record<string, number>>(Object.fromEntries(openLines.filter((l) => l.line_kind === "part").map((l) => [l.id, l.qty])));
  const [bikes, setBikes] = useState<Record<string, { condition: Condition; odometer_in: string; return_note: string }>>(
    Object.fromEntries(openLines.filter((l) => l.line_kind === "motorcycle").map((l) => [l.id, { condition: "good", odometer_in: "", return_note: "" }])),
  );
  const [err, setErr] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: () => {
      const body: ReturnIssuanceBody = {
        part_lines: Object.entries(parts).map(([line_id, returned_qty]) => ({ line_id, returned_qty })),
        bike_lines: Object.entries(bikes).map(([line_id, v]) => ({ line_id, condition: v.condition, odometer_in: v.odometer_in ? Number(v.odometer_in) : undefined, return_note: v.return_note || undefined })),
      };
      return issuanceApi.return(iss.id, body);
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not record the return."),
  });

  if (openLines.length === 0) return <Card className="p-4 text-sm text-slate-500">Nothing left to return. <Button variant="secondary" className="ml-2" onClick={onClose}>Close</Button></Card>;

  return (
    <Card className="p-4">
      <h3 className="mb-1 text-sm font-semibold text-slate-800">Record return</h3>
      <p className="mb-3 text-xs text-slate-400">Damaged bikes go to hold; unreturned items become a documented loss.</p>
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="space-y-2">
        {openLines.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-3 border-b border-slate-100 py-2 text-sm">
            <span className="min-w-0 flex-1">{lineTitle(l)}</span>
            {l.line_kind === "part" ? (
              <label className="flex items-center gap-1 text-xs text-slate-500">Returned
                <input type="number" min={0} max={l.qty} value={parts[l.id] ?? 0} onChange={(e) => setParts((p) => ({ ...p, [l.id]: Math.min(l.qty, Math.max(0, Number(e.target.value))) }))} className={`${IN} w-16 text-right`} /> / {l.qty}</label>
            ) : (
              <>
                <select className={IN} value={bikes[l.id]?.condition ?? "good"} onChange={(e) => setBikes((b) => ({ ...b, [l.id]: { ...b[l.id], condition: e.target.value as Condition } }))}>
                  {CONDITIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
                <input className={`${IN} w-24`} placeholder="Odometer" value={bikes[l.id]?.odometer_in ?? ""} onChange={(e) => setBikes((b) => ({ ...b, [l.id]: { ...b[l.id], odometer_in: e.target.value } }))} />
                {bikes[l.id]?.condition === "needs_attention" && (
                  <input className={`${IN} w-40`} placeholder="Damage note (hold reason)" value={bikes[l.id]?.return_note ?? ""} onChange={(e) => setBikes((b) => ({ ...b, [l.id]: { ...b[l.id], return_note: e.target.value } }))} />
                )}
              </>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button disabled={m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Record return"}</Button>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
      </div>
    </Card>
  );
}
