// Motorcycle unit detail — FormLayout with tabs (Identity / Lifecycle / Sale /
// Registration / Warranty / History), a status badge, the lifecycle timeline in the
// activity rail, related documents (sales invoice + transfers), an attachments slot for
// registration papers, and quick actions for the legal next transitions (illegal ones
// are simply not offered / disabled).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { DetailScaffold, FormLayout, Timeline } from "@/components/ds";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { bikeIssuesApi, issueStatusLabel } from "@/lib/bikeIssues";
import { useCustomers } from "@/lib/customers";
import { formatDate } from "@/lib/format";
import { type MotoUnit, motorcyclesApi, statusLabel } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";

type ActionModal = "reserve" | "sell" | "transfer" | "on_hold" | null;

export default function MotorcycleDetailPage() {
  const { id = "" } = useParams();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("motorcycle.manage");
  const qc = useQueryClient();
  const [modal, setModal] = useState<ActionModal>(null);
  const [err, setErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["moto", "unit", id],
    queryFn: () => motorcyclesApi.getUnit(id),
    enabled: Boolean(id),
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["moto", "unit", id] });
    void qc.invalidateQueries({ queryKey: ["moto", "units"] });
  };

  const transition = useMutation({
    mutationFn: (to: string) => motorcyclesApi.transition(id, to),
    onSuccess: invalidate,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Transition failed."),
  });

  return (
    <DetailScaffold loading={isLoading} error={error} notFound={!isLoading && !data}>
      {data && (
        <>
          <FormLayout
            title={data.chassis_number}
            subtitle={[data.model_name, data.variant_name, data.colour_name].filter(Boolean).join(" · ") || "Motorcycle unit"}
            status={data.status}
            backTo={{ href: "/motorcycles", label: "Motorcycles" }}
            actions={canManage ? (
              <LifecycleActions unit={data} onTransition={(to) => transition.mutate(to)} onModal={setModal} busy={transition.isPending} />
            ) : undefined}
            tabs={[
              { key: "identity", label: "Identity", content: <IdentityTab unit={data} canManage={canManage} onSaved={invalidate} /> },
              { key: "lifecycle", label: "Lifecycle", content: <LifecycleTab unit={data} canManage={canManage} onSaved={invalidate} /> },
              { key: "sale", label: "Sale", content: <SaleTab unit={data} /> },
              { key: "registration", label: "Registration", content: <RegistrationTab unit={data} canManage={canManage} onSaved={invalidate} /> },
              { key: "warranty", label: "Warranty", content: <WarrantyTab unit={data} /> },
              { key: "repairs", label: "Repairs", content: <RepairsTab unitId={data.id} /> },
              { key: "history", label: "History", content: <HistoryTab unit={data} /> },
            ]}
            activity={<Timeline items={data.events.slice().reverse().map((e) => ({
              title: eventTitle(e.event_type, e.to_status),
              detail: e.note ?? (e.from_branch_name && e.to_branch_name ? `${e.from_branch_name} → ${e.to_branch_name}` : undefined),
              time: formatDate(e.created_at),
            }))} />}
            related={<RelatedDocs unit={data} />}
            attachments={<RegistrationPapers unit={data} />}
          />
          {err && <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
          {modal === "reserve" && <ReserveModal unit={data} onClose={() => setModal(null)} onDone={() => { setModal(null); invalidate(); }} />}
          {modal === "sell" && <SellModal unit={data} onClose={() => setModal(null)} onDone={() => { setModal(null); invalidate(); }} />}
          {modal === "transfer" && <TransferModal unit={data} onClose={() => setModal(null)} onDone={() => { setModal(null); invalidate(); }} />}
          {modal === "on_hold" && <OnHoldModal unit={data} onClose={() => setModal(null)} onDone={() => { setModal(null); invalidate(); }} />}
        </>
      )}
    </DetailScaffold>
  );
}

function eventTitle(type: string, to?: string | null): string {
  if (type === "created") return "Unit received";
  if (type === "reserved") return "Reserved for customer";
  if (type === "sold") return "Sold";
  if (type === "transfer") return "Branch transfer";
  if (type === "status_change" && to) return `Moved to ${statusLabel(to)}`;
  return statusLabel(type);
}

// ---- quick actions --------------------------------------------------------
// Reserve / sell / on_hold open modals (they need a customer, an invoice, or a reason);
// the remaining legal moves (assembled/unassembled) are one-click. Illegal moves are
// never offered — allowed_next comes from the server state machine.
function LifecycleActions({ unit, onTransition, onModal, busy }: {
  unit: MotoUnit; onTransition: (to: string) => void; onModal: (m: ActionModal) => void; busy: boolean;
}) {
  const next = unit.allowed_next;
  const modalStatuses = ["reserved", "sold", "on_hold"];
  return (
    <>
      {next.filter((s) => !modalStatuses.includes(s)).map((s) => (
        <Button key={s} variant="secondary" disabled={busy} onClick={() => onTransition(s)}>
          Mark {statusLabel(s)}
        </Button>
      ))}
      {next.includes("on_hold") && <Button variant="secondary" onClick={() => onModal("on_hold")}>Put on hold…</Button>}
      {next.includes("reserved") && <Button variant="secondary" onClick={() => onModal("reserve")}>Reserve…</Button>}
      {next.includes("sold") && <Button onClick={() => onModal("sell")}>Sell…</Button>}
      {unit.status !== "sold" && <Button variant="ghost" onClick={() => onModal("transfer")}>Transfer…</Button>}
    </>
  );
}

// ---- tabs -----------------------------------------------------------------
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-line py-2 text-sm last:border-0">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium text-content">{children ?? "—"}</span>
    </div>
  );
}

function money(v: number | null): string {
  return v == null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function IdentityTab({ unit, canManage, onSaved }: { unit: MotoUnit; canManage: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="max-w-xl">
      <Row label="Chassis number"><span className="font-mono">{unit.chassis_number}</span></Row>
      <Row label="Engine number"><span className="font-mono">{unit.engine_number ?? "—"}</span></Row>
      <Row label="Model">{unit.model_name}</Row>
      <Row label="Variant">{unit.variant_name}</Row>
      <Row label="Colour">{unit.colour_name}</Row>
      <Row label="Year">{unit.year}</Row>
      <Row label="Country of origin">{unit.country_of_origin}</Row>
      <Row label="Supplier">{unit.supplier_name}</Row>
      <Row label="Container ref">{unit.container_ref}</Row>
      <Row label="Date received">{unit.date_received}</Row>
      <Row label="Branch">{unit.branch_name}</Row>
      <Row label="Location">{unit.warehouse_name}</Row>
      <Row label="Internal location">{unit.internal_location}</Row>
      {canManage && <div className="mt-3"><Button variant="secondary" onClick={() => setEditing(true)}>Edit origin</Button></div>}
      {editing && <EditUnitModal unit={unit} fields={["country_of_origin"]} title="Edit country of origin" onClose={() => setEditing(false)} onDone={() => { setEditing(false); onSaved(); }} />}
    </div>
  );
}

function LifecycleTab({ unit, canManage, onSaved }: { unit: MotoUnit; canManage: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="max-w-xl">
      <Row label="Status">{statusLabel(unit.status)}</Row>
      <Row label="Inspected">{unit.inspected ? "Yes" : "No"}</Row>
      {unit.status === "on_hold" ? (
        <Row label="Hold reason">{unit.hold_reason ?? "—"}</Row>
      ) : unit.hold_reason ? (
        <Row label="Last hold reason">{unit.hold_reason}</Row>
      ) : null}
      <Row label="Held for order">{unit.reserved_so_number ?? "—"}</Row>
      <Row label="Next actions">{unit.allowed_next.length ? unit.allowed_next.map(statusLabel).join(", ") : "None (terminal)"}</Row>
      {canManage && <div className="mt-3"><Button variant="secondary" onClick={() => setEditing(true)}>Edit inspection</Button></div>}
      {editing && <EditUnitModal unit={unit} fields={["inspected"]} title="Edit inspection" onClose={() => setEditing(false)} onDone={() => { setEditing(false); onSaved(); }} />}
    </div>
  );
}

function SaleTab({ unit }: { unit: MotoUnit }) {
  return (
    <div className="max-w-xl">
      <Row label="Customer">{unit.customer_name}</Row>
      <Row label="Invoice">{unit.sold_invoice_number ?? "—"}</Row>
      <Row label="Selling price">{money(unit.selling_price)}</Row>
      <Row label="Price charged">{money(unit.price_charged)}</Row>
      <Row label="Payment status">{statusLabel(unit.payment_status)}</Row>
    </div>
  );
}

function RegistrationTab({ unit, canManage, onSaved }: { unit: MotoUnit; canManage: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="max-w-xl">
      <Row label="Registered">{unit.registered ? "Yes" : "No"}</Row>
      <Row label="Registration number">{unit.registration_number ?? "—"}</Row>
      <Row label="Papers received">{unit.registration_papers_received ? "Yes" : "No"}</Row>
      {canManage && <div className="mt-3"><Button variant="secondary" onClick={() => setEditing(true)}>Edit registration</Button></div>}
      {editing && <EditUnitModal unit={unit} fields={["registered", "registration_number", "registration_papers_received"]} title="Edit registration" onClose={() => setEditing(false)} onDone={() => { setEditing(false); onSaved(); }} />}
    </div>
  );
}

function WarrantyTab({ unit }: { unit: MotoUnit }) {
  return (
    <div className="max-w-xl">
      <Row label="Warranty start">{unit.warranty_start}</Row>
      <Row label="Warranty end">{unit.warranty_end}</Row>
    </div>
  );
}

function HistoryTab({ unit }: { unit: MotoUnit }) {
  if (unit.events.length === 0) return <p className="text-sm text-content-subtle">No lifecycle events yet.</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
          <th className="py-2 pr-4 font-medium">Event</th>
          <th className="py-2 pr-4 font-medium">Detail</th>
          <th className="py-2 font-medium">When</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {unit.events.slice().reverse().map((e) => (
          <tr key={e.id} className="text-content-muted">
            <td className="py-2 pr-4">{eventTitle(e.event_type, e.to_status)}</td>
            <td className="py-2 pr-4">
              {e.note ?? (e.from_branch_name && e.to_branch_name ? `${e.from_branch_name} → ${e.to_branch_name}` : "—")}
            </td>
            <td className="py-2 text-content-subtle">{formatDate(e.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Repair history for this chassis: which parts were consumed, and when. Read-only here —
// repairs are opened/resolved from the Bike Issues module.
function RepairsTab({ unitId }: { unitId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["bike-issues", "unit", unitId],
    queryFn: () => bikeIssuesApi.list({ unit_id: unitId, page_size: 100 }),
  });
  if (isLoading) return <p className="text-sm text-content-subtle">Loading repairs…</p>;
  const issues = data?.items ?? [];
  if (issues.length === 0) return <p className="text-sm text-content-subtle">No repair issues for this bike.</p>;
  return (
    <div className="space-y-4">
      {issues.map((i) => (
        <div key={i.id} className="rounded-card border border-line p-3">
          <div className="mb-1 flex items-center justify-between gap-2">
            <Link to={`/bike-issues/${i.id}`} className="font-mono text-[13px] font-medium text-brand-600 hover:underline">{i.issue_number}</Link>
            <span className="text-xs text-muted">{issueStatusLabel(i.status)} · {formatDate(i.reported_at)}</span>
          </div>
          <div className="text-sm text-content-muted">{i.problem_description}</div>
          {i.lines.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-muted">
              {i.lines.map((l) => (
                <li key={l.id} className="flex justify-between">
                  <span>{l.name ?? "—"} <span className="font-mono text-content-subtle">{l.sku}</span></span>
                  <span>{l.quantity}× {l.consumed ? "consumed" : "planned"}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

function RelatedDocs({ unit }: { unit: MotoUnit }) {
  const transfers = unit.events.filter((e) => e.event_type === "transfer");
  const hasAny = unit.sold_invoice_number || unit.reserved_so_number || transfers.length > 0;
  if (!hasAny) return <p className="text-sm text-content-subtle">No linked documents.</p>;
  return (
    <ul className="space-y-2 text-sm">
      {unit.sold_invoice_number && (
        <li className="flex justify-between"><span className="text-muted">Invoice</span>
          <Link to="/sales" className="font-medium text-brand-600 hover:underline">{unit.sold_invoice_number}</Link></li>
      )}
      {unit.reserved_so_number && (
        <li className="flex justify-between"><span className="text-muted">Sales order</span>
          <Link to="/sales" className="font-medium text-brand-600 hover:underline">{unit.reserved_so_number}</Link></li>
      )}
      {transfers.map((t) => (
        <li key={t.id} className="flex justify-between">
          <span className="text-muted">Transfer</span>
          <span className="font-medium text-content">{t.from_branch_name} → {t.to_branch_name}</span>
        </li>
      ))}
    </ul>
  );
}

function RegistrationPapers({ unit }: { unit: MotoUnit }) {
  return (
    <p className="text-sm text-content-subtle">
      {unit.registration_papers_received
        ? "Registration papers marked as received."
        : "No registration papers on file yet."}
    </p>
  );
}

// ---- action modals --------------------------------------------------------
const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function ModalField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-content-muted">{label}</span>{children}</label>;
}

function ReserveModal({ unit, onClose, onDone }: { unit: MotoUnit; onClose: () => void; onDone: () => void }) {
  const customers = useCustomers();
  const [customerId, setCustomerId] = useState("");
  const [soId, setSoId] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => motorcyclesApi.reserve(unit.id, { customer_id: customerId, sales_order_id: soId || undefined }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not reserve."),
  });
  return (
    <Modal title="Reserve this unit" size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!customerId || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Reserving…" : "Reserve"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <ModalField label="Customer *">
          <select className={INPUT} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            <option value="">Select a customer…</option>
            {(customers.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </ModalField>
        <ModalField label="Sales order ID (optional)"><input className={INPUT} value={soId} onChange={(e) => setSoId(e.target.value)} placeholder="Link an existing sales order" /></ModalField>
      </div>
    </Modal>
  );
}

function SellModal({ unit, onClose, onDone }: { unit: MotoUnit; onClose: () => void; onDone: () => void }) {
  const [invoiceId, setInvoiceId] = useState("");
  const [price, setPrice] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => motorcyclesApi.sell(unit.id, { invoice_id: invoiceId, price_charged: price ? Number(price) : undefined }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not sell."),
  });
  return (
    <Modal title="Sell this unit" size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!invoiceId || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Selling…" : "Sell"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <p className="text-xs text-muted">The invoice is created in the Sales module; linking it here records the sale against this chassis.</p>
        <ModalField label="Invoice ID *"><input className={INPUT} value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} placeholder="Existing sales invoice" /></ModalField>
        <ModalField label="Price charged (optional)"><input type="number" min={0} className={INPUT} value={price} onChange={(e) => setPrice(e.target.value)} /></ModalField>
      </div>
    </Modal>
  );
}

function TransferModal({ unit, onClose, onDone }: { unit: MotoUnit; onClose: () => void; onDone: () => void }) {
  const { list: branches } = useBranches();
  const [toBranch, setToBranch] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => motorcyclesApi.transfer(unit.id, { to_branch_id: toBranch, note: note || undefined }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not transfer."),
  });
  return (
    <Modal title="Transfer this unit" size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!toBranch || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Transferring…" : "Transfer"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <ModalField label="Destination branch *">
          <select className={INPUT} value={toBranch} onChange={(e) => setToBranch(e.target.value)}>
            <option value="">Select a branch…</option>
            {branches.filter((b) => b.id !== unit.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </ModalField>
        <ModalField label="Note (optional)"><input className={INPUT} value={note} onChange={(e) => setNote(e.target.value)} /></ModalField>
      </div>
    </Modal>
  );
}

function OnHoldModal({ unit, onClose, onDone }: { unit: MotoUnit; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => motorcyclesApi.transition(unit.id, "on_hold", { hold_reason: reason.trim() }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not put on hold."),
  });
  return (
    <Modal title="Put this unit on hold" size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={!reason.trim() || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Holding…" : "Put on hold"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <p className="text-xs text-muted">Holding removes any customer and takes the unit out of sale until it's cleared.</p>
        <ModalField label="Hold reason *">
          <input className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Damaged in transit, missing parts" autoFocus />
        </ModalField>
      </div>
    </Modal>
  );
}

function EditUnitModal({ unit, fields, title, onClose, onDone }: {
  unit: MotoUnit; fields: string[]; title: string; onClose: () => void; onDone: () => void;
}) {
  const [form, setForm] = useState<Record<string, unknown>>({
    inspected: unit.inspected,
    registered: unit.registered,
    registration_number: unit.registration_number ?? "",
    registration_papers_received: unit.registration_papers_received,
    country_of_origin: unit.country_of_origin ?? "",
  });
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { version: unit.version };
      for (const f of fields) body[f] = form[f] === "" ? null : form[f];
      return motorcyclesApi.updateUnit(unit.id, body);
    },
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save."),
  });
  return (
    <Modal title={title} size="md" onClose={onClose} footer={
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button disabled={m.isPending} onClick={() => { setErr(null); m.mutate(); }}>{m.isPending ? "Saving…" : "Save"}</Button></>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        {fields.includes("inspected") && (
          <label className="flex items-center gap-2 text-sm text-content">
            <input type="checkbox" checked={Boolean(form.inspected)} onChange={(e) => setForm((f) => ({ ...f, inspected: e.target.checked }))} />
            Inspected
          </label>
        )}
        {fields.includes("registered") && (
          <label className="flex items-center gap-2 text-sm text-content">
            <input type="checkbox" checked={Boolean(form.registered)} onChange={(e) => setForm((f) => ({ ...f, registered: e.target.checked }))} />
            Registered
          </label>
        )}
        {fields.includes("registration_number") && (
          <ModalField label="Registration number">
            <input className={INPUT} value={String(form.registration_number ?? "")} onChange={(e) => setForm((f) => ({ ...f, registration_number: e.target.value }))} />
          </ModalField>
        )}
        {fields.includes("country_of_origin") && (
          <ModalField label="Country of origin">
            <input className={INPUT} list="origin-suggestions" placeholder="e.g. India, Congo, Kenya" value={String(form.country_of_origin ?? "")} onChange={(e) => setForm((f) => ({ ...f, country_of_origin: e.target.value }))} />
            <datalist id="origin-suggestions"><option value="India" /><option value="Congo" /><option value="Kenya" /></datalist>
          </ModalField>
        )}
        {fields.includes("registration_papers_received") && (
          <label className="flex items-center gap-2 text-sm text-content">
            <input type="checkbox" checked={Boolean(form.registration_papers_received)} onChange={(e) => setForm((f) => ({ ...f, registration_papers_received: e.target.checked }))} />
            Registration papers received
          </label>
        )}
      </div>
    </Modal>
  );
}
