// Customer Handover list + "New Handover" flow. New = enter/scan a chassis, which looks
// up the sold unit + its invoice and shows an auto-fill preview; creating the draft
// navigates to the detail page where the checklist, training, payment and approvals are
// filled and the record is completed + printed.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Plus, ScanLine, Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { type Handover, type HandoverLookup, handoversApi } from "@/lib/handovers";

const INPUT =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function HandoversPage() {
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const canManage = hasPermission("motorcycle.manage");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showNew, setShowNew] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["handovers", "list", search, statusFilter],
    queryFn: () => handoversApi.list({ search: search.trim() || undefined, status: statusFilter || undefined }),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader
        title="Customer Handovers"
        description="The signed record that a customer physically received their motorcycle: pre-delivery checklist, training, accessories, payment and quality sign-off. Completing a handover marks the bike delivered and starts its warranty."
        actions={canManage ? <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New handover</Button> : undefined}
      />

      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-2 p-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              className={`${INPUT} pl-9`}
              placeholder="Search handover #, chassis, or customer"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select className={`${INPUT} w-40`} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="DRAFT">Draft</option>
            <option value="COMPLETED">Completed</option>
          </select>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {isFetching && !data ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : !data || data.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <ClipboardCheck className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            No handovers yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Handover #</th>
                <th className="px-4 py-2.5 font-medium">Customer</th>
                <th className="px-4 py-2.5 font-medium">Motorcycle</th>
                <th className="px-4 py-2.5 font-medium">Chassis</th>
                <th className="px-4 py-2.5 font-medium">Delivery date</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((h) => (
                <tr key={h.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/handovers/${h.id}`)}>
                  <td className="px-4 py-3 font-mono text-[13px] font-medium">{h.handover_no}</td>
                  <td className="px-4 py-3 text-slate-700">{h.full_name ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{[h.model_name, h.colour_name].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="px-4 py-3 font-mono text-[13px] text-slate-600">{h.chassis_number ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{h.delivery_date ?? "—"}</td>
                  <td className="px-4 py-3"><StatusBadge status={h.status.toLowerCase()} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {showNew && <NewHandoverModal onClose={() => setShowNew(false)} onCreated={(id) => navigate(`/handovers/${id}`)} />}
    </div>
  );
}

function NewHandoverModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const [chassis, setChassis] = useState("");
  const [preview, setPreview] = useState<HandoverLookup | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const lookup = useMutation({
    mutationFn: () => handoversApi.lookup(chassis.trim()),
    onSuccess: (p) => { setPreview(p); setErr(null); },
    onError: (e) => { setPreview(null); setErr(e instanceof ApiError ? e.message : "Lookup failed."); },
  });

  const create = useMutation({
    mutationFn: () => handoversApi.create({ unit_id: preview!.unit_id, invoice_id: preview!.invoice_id ?? undefined }),
    onSuccess: (h) => { void qc.invalidateQueries({ queryKey: ["handovers"] }); onCreated(h.id); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create the handover."),
  });

  const existing = preview?.existing_handover_id ?? null;

  return (
    <Modal
      title="New customer handover"
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          {existing ? (
            <Button onClick={() => onCreated(existing)}>Open existing handover</Button>
          ) : (
            <Button
              disabled={!preview || create.isPending}
              onClick={() => { setErr(null); create.mutate(); }}
            >
              {create.isPending ? "Creating…" : "Create draft"}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Chassis / VIN number</span>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <ScanLine className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                autoFocus
                className={`${INPUT} pl-9`}
                placeholder="Scan or type the chassis number"
                value={chassis}
                onChange={(e) => setChassis(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && chassis.trim()) lookup.mutate(); }}
              />
            </div>
            <Button variant="secondary" disabled={!chassis.trim() || lookup.isPending} onClick={() => lookup.mutate()}>
              {lookup.isPending ? "Looking…" : "Look up"}
            </Button>
          </div>
        </label>

        {preview && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
            {existing && (
              <div className="mb-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
                This bike already has a handover record. Open it instead of creating a second one.
              </div>
            )}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <Info label="Motorcycle" value={[preview.model_name, preview.colour_name].filter(Boolean).join(" · ")} />
              <Info label="Chassis" value={preview.chassis_number} mono />
              <Info label="Customer" value={preview.customer_name} />
              <Info label="Invoice" value={preview.invoice_number} />
              <Info label="Salesperson" value={preview.salesperson_display} />
              <Info label="Branch" value={preview.branch_name} />
              <Info label="Invoice amount" value={`ZMW ${formatNumber(preview.invoice_amount_zmw, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
              <Info label="Balance" value={`ZMW ${formatNumber(preview.balance_zmw, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
            </div>
            {!preview.invoice_id && (
              <div className="mt-2 text-xs text-slate-500">No linked invoice (imported historical sale) — the amount is taken from the bike's sale price and can be adjusted on the form.</div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

function Info({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-500">{label}</span>
      <span className={`font-medium text-slate-800 ${mono ? "font-mono text-[13px]" : ""}`}>{value || "—"}</span>
    </div>
  );
}

export type { Handover };
