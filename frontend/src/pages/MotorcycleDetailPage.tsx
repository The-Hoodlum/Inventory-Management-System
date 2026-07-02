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
import { useCustomers } from "@/lib/customers";
import { formatDate } from "@/lib/format";
import { type MotoUnit, motorcyclesApi, statusLabel } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";

type ActionModal = "reserve" | "sell" | "transfer" | null;

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
              { key: "identity", label: "Identity", content: <IdentityTab unit={data} /> },
              { key: "lifecycle", label: "Lifecycle", content: <LifecycleTab unit={data} /> },
              { key: "sale", label: "Sale", content: <SaleTab unit={data} /> },
              { key: "registration", label: "Registration", content: <RegistrationTab unit={data} canManage={canManage} onSaved={invalidate} /> },
              { key: "warranty", label: "Warranty", content: <WarrantyTab unit={data} /> },
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
function LifecycleActions({ unit, onTransition, onModal, busy }: {
  unit: MotoUnit; onTransition: (to: string) => void; onModal: (m: ActionModal) => void; busy: boolean;
}) {
  const next = unit.allowed_next;
  const canTransfer = unit.status !== "cancelled";
  return (
    <>
      {next.filter((s) => s !== "reserved" && s !== "sold").map((s) => (
        <Button key={s} variant="secondary" disabled={busy} onClick={() => onTransition(s)}>
          {s === "cancelled" ? "Cancel unit" : `Mark ${statusLabel(s)}`}
        </Button>
      ))}
      {next.includes("reserved") && <Button variant="secondary" onClick={() => onModal("reserve")}>Reserve…</Button>}
      {next.includes("sold") && <Button onClick={() => onModal("sell")}>Sell…</Button>}
      {canTransfer && <Button variant="ghost" onClick={() => onModal("transfer")}>Transfer…</Button>}
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

function IdentityTab({ unit }: { unit: MotoUnit }) {
  return (
    <div className="max-w-xl">
      <Row label="Chassis number"><span className="font-mono">{unit.chassis_number}</span></Row>
      <Row label="Engine number"><span className="font-mono">{unit.engine_number ?? "—"}</span></Row>
      <Row label="Model">{unit.model_name}</Row>
      <Row label="Variant">{unit.variant_name}</Row>
      <Row label="Colour">{unit.colour_name}</Row>
      <Row label="Year">{unit.year}</Row>
      <Row label="Supplier">{unit.supplier_name}</Row>
      <Row label="Container ref">{unit.container_ref}</Row>
      <Row label="Date received">{unit.date_received}</Row>
      <Row label="Branch">{unit.branch_name}</Row>
      <Row label="Location">{unit.warehouse_name}</Row>
      <Row label="Internal location">{unit.internal_location}</Row>
    </div>
  );
}

function LifecycleTab({ unit }: { unit: MotoUnit }) {
  return (
    <div className="max-w-xl">
      <Row label="Status">{statusLabel(unit.status)}</Row>
      <Row label="Inspection">{statusLabel(unit.inspection_status)}</Row>
      <Row label="Assembly">{statusLabel(unit.assembly_status)}</Row>
      <Row label="Held for order">{unit.reserved_so_number ?? "—"}</Row>
      <Row label="Next actions">{unit.allowed_next.length ? unit.allowed_next.map(statusLabel).join(", ") : "None (terminal)"}</Row>
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
      <Row label="Registration status">{statusLabel(unit.registration_status)}</Row>
      <Row label="Registration number">{unit.registration_number ?? "—"}</Row>
      <Row label="Papers received">{unit.registration_papers_received ? "Yes" : "No"}</Row>
      {canManage && <div className="mt-3"><Button variant="secondary" onClick={() => setEditing(true)}>Edit registration</Button></div>}
      {editing && <EditUnitModal unit={unit} fields={["registration_number", "registration_papers_received"]} title="Edit registration" onClose={() => setEditing(false)} onDone={() => { setEditing(false); onSaved(); }} />}
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

function EditUnitModal({ unit, fields, title, onClose, onDone }: {
  unit: MotoUnit; fields: string[]; title: string; onClose: () => void; onDone: () => void;
}) {
  const [form, setForm] = useState<Record<string, unknown>>({
    registration_number: unit.registration_number ?? "",
    registration_papers_received: unit.registration_papers_received,
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
        {fields.includes("registration_number") && (
          <ModalField label="Registration number">
            <input className={INPUT} value={String(form.registration_number ?? "")} onChange={(e) => setForm((f) => ({ ...f, registration_number: e.target.value }))} />
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
