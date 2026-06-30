// Motorcycle unit detail — assembled from the shared FormLayout: tabbed record
// (Identity / Lifecycle / Sale / Registration / Warranty / History), status badge,
// lifecycle timeline in the activity rail, linked sales documents in the related-docs
// rail, a registration-papers attachments slot, and quick actions for the LEGAL next
// transitions (disabled/omitted when illegal). All writes go through the audited API.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, FileText, Receipt } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { DetailScaffold, FormLayout, Timeline, type TimelineItem } from "@/components/ds";
import { Button } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { motorcyclesApi, type MotorcycleUnit, type UnitStatus } from "@/lib/motorcycles";
import { useBranches, useWarehouses } from "@/lib/refdata";
import type { Page } from "@/types/api";

const INPUT =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export default function MotorcycleDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("motorcycle.manage");
  const [action, setAction] = useState<"reserve" | "sell" | "transfer" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const { data: unit, isLoading, error } = useQuery({
    queryKey: ["motorcycle", id],
    queryFn: () => motorcyclesApi.get(id),
  });

  const refresh = (u: MotorcycleUnit) => {
    qc.setQueryData(["motorcycle", id], u);
    qc.invalidateQueries({ queryKey: ["motorcycles"] });
  };

  const transition = useMutation({
    mutationFn: (to: string) => motorcyclesApi.transition(id, to),
    onSuccess: refresh,
    onError: (e) => setMsg(e instanceof ApiError ? e.message : "Transition failed."),
  });

  return (
    <DetailScaffold loading={isLoading} error={error} notFound={!isLoading && !unit}>
      {unit && (
        <>
          {msg && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{msg}</div>}
          <FormLayout
            title={unit.chassis_number}
            subtitle={[unit.model, unit.variant, unit.colour].filter(Boolean).join(" · ") || "Serialized unit"}
            status={unit.status}
            backTo={{ href: "/motorcycles", label: "Motorcycles" }}
            actions={
              canManage ? (
                <ActionBar
                  unit={unit}
                  pending={transition.isPending}
                  onTransition={(to) => { setMsg(null); transition.mutate(to); }}
                  onReserve={() => setAction("reserve")}
                  onSell={() => setAction("sell")}
                  onTransfer={() => setAction("transfer")}
                />
              ) : undefined
            }
            tabs={[
              { key: "identity", label: "Identity", content: <IdentityTab unit={unit} /> },
              { key: "lifecycle", label: "Lifecycle", content: <LifecycleTab unit={unit} /> },
              { key: "sale", label: "Sale", content: <SaleTab unit={unit} /> },
              { key: "registration", label: "Registration", content: <RegistrationTab unit={unit} /> },
              { key: "warranty", label: "Warranty", content: <WarrantyTab unit={unit} /> },
              { key: "history", label: "History", content: <HistoryTab unit={unit} /> },
            ]}
            activity={<Timeline items={unitTimeline(unit)} />}
            related={<RelatedDocs unit={unit} />}
            attachments={
              <p className="text-sm text-muted">
                Registration papers:{" "}
                <span className={unit.registration_papers_received ? "text-emerald-600" : "text-content-subtle"}>
                  {unit.registration_papers_received ? "received" : "not received"}
                </span>
              </p>
            }
          />
          {action === "reserve" && <ReserveModal unit={unit} onClose={() => setAction(null)} onDone={(u) => { refresh(u); setAction(null); }} />}
          {action === "sell" && <SellModal unit={unit} onClose={() => setAction(null)} onDone={(u) => { refresh(u); setAction(null); }} />}
          {action === "transfer" && <TransferModal unit={unit} onClose={() => setAction(null)} onDone={(u) => { refresh(u); setAction(null); }} />}
        </>
      )}
    </DetailScaffold>
  );
}

// ------------------------------ quick actions ----------------------------- #
function ActionBar({
  unit, pending, onTransition, onReserve, onSell, onTransfer,
}: {
  unit: MotorcycleUnit;
  pending: boolean;
  onTransition: (to: string) => void;
  onReserve: () => void;
  onSell: () => void;
  onTransfer: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {unit.allowed_next.map((to: UnitStatus) => {
        if (to === "reserved") return <Button key={to} variant="secondary" onClick={onReserve}>Reserve</Button>;
        if (to === "sold") return <Button key={to} onClick={onSell}>Sell</Button>;
        return (
          <Button key={to} variant="secondary" disabled={pending} onClick={() => onTransition(to)}>
            {titleCase(to)}
          </Button>
        );
      })}
      {unit.status !== "cancelled" && (
        <Button variant="ghost" onClick={onTransfer}>
          <ArrowLeftRight className="h-4 w-4" /> Transfer
        </Button>
      )}
    </div>
  );
}

// --------------------------------- tabs ----------------------------------- #
function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-sm text-content">{value ?? "—"}</div>
    </div>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">{children}</div>;
}

function IdentityTab({ unit }: { unit: MotorcycleUnit }) {
  return (
    <Grid>
      <Info label="Chassis number" value={<span className="font-mono">{unit.chassis_number}</span>} />
      <Info label="Engine number" value={unit.engine_number} />
      <Info label="Model" value={unit.model} />
      <Info label="Variant" value={unit.variant} />
      <Info label="Colour" value={unit.colour} />
      <Info label="Year" value={unit.year} />
      <Info label="Supplier" value={unit.supplier_name} />
      <Info label="Container ref" value={unit.container_ref} />
      <Info label="Date received" value={formatDate(unit.date_received)} />
      <Info label="Branch" value={unit.branch_name} />
      <Info label="Location" value={unit.warehouse_name} />
      <Info label="Internal location" value={unit.internal_location} />
    </Grid>
  );
}

function LifecycleTab({ unit }: { unit: MotorcycleUnit }) {
  return (
    <Grid>
      <Info label="Status" value={titleCase(unit.status)} />
      <Info label="Inspection" value={titleCase(unit.inspection_status)} />
      <Info label="Assembly" value={titleCase(unit.assembly_status)} />
      <Info label="Reserved" value={unit.reserved ? "Yes" : "No"} />
      <Info label="Sold" value={unit.sold ? "Yes" : "No"} />
      <Info
        label="Next steps"
        value={unit.allowed_next.length ? unit.allowed_next.map((s) => titleCase(s)).join(", ") : "Terminal"}
      />
    </Grid>
  );
}

function SaleTab({ unit }: { unit: MotorcycleUnit }) {
  return (
    <Grid>
      <Info label="Customer" value={unit.customer_name} />
      <Info label="Sales order" value={unit.so_number} />
      <Info label="Invoice" value={unit.invoice_number} />
      <Info label="Selling price" value={formatNumber(unit.selling_price, { minimumFractionDigits: 2 })} />
      <Info label="Price charged" value={formatNumber(unit.price_charged, { minimumFractionDigits: 2 })} />
      <Info label="Payment" value={titleCase(unit.payment_status)} />
    </Grid>
  );
}

function RegistrationTab({ unit }: { unit: MotorcycleUnit }) {
  return (
    <Grid>
      <Info label="Status" value={titleCase(unit.registration_status)} />
      <Info label="Registration no." value={unit.registration_number} />
      <Info label="Papers received" value={unit.registration_papers_received ? "Yes" : "No"} />
    </Grid>
  );
}

function WarrantyTab({ unit }: { unit: MotorcycleUnit }) {
  return (
    <Grid>
      <Info label="Warranty start" value={formatDate(unit.warranty_start)} />
      <Info label="Warranty end" value={formatDate(unit.warranty_end)} />
    </Grid>
  );
}

function HistoryTab({ unit }: { unit: MotorcycleUnit }) {
  if (unit.events.length === 0) return <p className="text-sm text-muted">No events yet.</p>;
  return (
    <div className="overflow-hidden rounded-card border border-line">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line bg-canvas text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-3 py-2 font-medium">When</th>
            <th className="px-3 py-2 font-medium">Event</th>
            <th className="px-3 py-2 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {[...unit.events].reverse().map((e) => (
            <tr key={e.id} className="text-content-muted">
              <td className="px-3 py-2 whitespace-nowrap">{formatDate(e.created_at)}</td>
              <td className="px-3 py-2">{titleCase(e.event_type)}</td>
              <td className="px-3 py-2">
                {e.from_status && e.to_status ? `${titleCase(e.from_status)} → ${titleCase(e.to_status)}` : null}
                {e.event_type === "transfer" && `${e.from_branch_name ?? "—"} → ${e.to_branch_name ?? "—"}`}
                {e.note ? <span className="text-content-subtle"> · {e.note}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function unitTimeline(unit: MotorcycleUnit): TimelineItem[] {
  return unit.events.map((e) => ({
    title: titleCase(e.event_type),
    detail:
      e.from_status && e.to_status
        ? `${titleCase(e.from_status)} → ${titleCase(e.to_status)}`
        : e.event_type === "transfer"
          ? `${e.from_branch_name ?? "—"} → ${e.to_branch_name ?? "—"}`
          : e.note ?? undefined,
    time: formatDate(e.created_at),
  }));
}

function RelatedDocs({ unit }: { unit: MotorcycleUnit }) {
  const docs = [
    unit.so_number && { icon: <FileText className="h-4 w-4" />, label: unit.so_number, sub: "Sales order" },
    unit.invoice_number && { icon: <Receipt className="h-4 w-4" />, label: unit.invoice_number, sub: "Invoice" },
  ].filter(Boolean) as { icon: ReactNode; label: string; sub: string }[];
  if (docs.length === 0) return <p className="text-sm text-content-subtle">No linked documents.</p>;
  return (
    <ul className="space-y-2">
      {docs.map((d) => (
        <li key={d.label} className="flex items-center gap-2 text-sm">
          <span className="text-content-subtle">{d.icon}</span>
          <span className="text-content">{d.label}</span>
          <span className="ml-auto text-2xs text-content-subtle">{d.sub}</span>
        </li>
      ))}
    </ul>
  );
}

// -------------------------------- modals ---------------------------------- #
function ModalField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}

function ReserveModal({ unit, onClose, onDone }: { unit: MotorcycleUnit; onClose: () => void; onDone: (u: MotorcycleUnit) => void }) {
  const [customerId, setCustomerId] = useState(unit.customer_id ?? "");
  const [soId, setSoId] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const { data: customers } = useQuery({
    queryKey: ["customers", "all"],
    queryFn: () => api.get<Page<{ id: string; name: string }>>("/customers?page_size=200"),
  });
  const { data: orders } = useQuery({
    queryKey: ["sales", "orders", customerId],
    queryFn: () => api.get<Page<{ id: string; so_number: string }>>(`/sales/orders?customer_id=${customerId}&limit=50`),
    enabled: !!customerId,
  });
  const m = useMutation({
    mutationFn: () => motorcyclesApi.reserve(unit.id, { customer_id: customerId, sales_order_id: soId || undefined }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Reserve failed."),
  });
  return (
    <Modal title="Reserve unit" onClose={onClose} size="md"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!customerId || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>Reserve</Button></>}>
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="space-y-3">
        <ModalField label="Customer *">
          <select className={INPUT} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            <option value="">Select…</option>
            {(customers?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </ModalField>
        <ModalField label="Link sales order (optional)">
          <select className={INPUT} value={soId} onChange={(e) => setSoId(e.target.value)} disabled={!customerId}>
            <option value="">None</option>
            {(orders?.items ?? []).map((o) => <option key={o.id} value={o.id}>{o.so_number}</option>)}
          </select>
        </ModalField>
      </div>
    </Modal>
  );
}

function SellModal({ unit, onClose, onDone }: { unit: MotorcycleUnit; onClose: () => void; onDone: (u: MotorcycleUnit) => void }) {
  const [invoiceId, setInvoiceId] = useState("");
  const [price, setPrice] = useState(String(unit.selling_price || ""));
  const [err, setErr] = useState<string | null>(null);
  const { data: invoices } = useQuery({
    queryKey: ["sales", "invoices", "all"],
    queryFn: () => api.get<Page<{ id: string; invoice_number: string }>>("/sales/invoices?limit=50"),
  });
  const m = useMutation({
    mutationFn: () => motorcyclesApi.sell(unit.id, { invoice_id: invoiceId, price_charged: price ? Number(price) : undefined }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Sell failed."),
  });
  return (
    <Modal title="Sell unit" onClose={onClose} size="md"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!invoiceId || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>Sell</Button></>}>
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="space-y-3">
        <ModalField label="Invoice * (the existing sales invoice)">
          <select className={INPUT} value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)}>
            <option value="">Select…</option>
            {(invoices?.items ?? []).map((i) => <option key={i.id} value={i.id}>{i.invoice_number}</option>)}
          </select>
        </ModalField>
        <ModalField label="Price charged">
          <input className={INPUT} type="number" value={price} onChange={(e) => setPrice(e.target.value)} />
        </ModalField>
      </div>
    </Modal>
  );
}

function TransferModal({ unit, onClose, onDone }: { unit: MotorcycleUnit; onClose: () => void; onDone: (u: MotorcycleUnit) => void }) {
  const { list: branches } = useBranches();
  const { list: warehouses } = useWarehouses();
  const [toBranch, setToBranch] = useState("");
  const [toWh, setToWh] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => motorcyclesApi.transfer(unit.id, { to_branch_id: toBranch, to_warehouse_id: toWh || undefined, note: note || undefined }),
    onSuccess: onDone,
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Transfer failed."),
  });
  const whOptions = warehouses.filter((w) => !toBranch || w.branch_id === toBranch);
  return (
    <Modal title="Transfer unit to another branch" onClose={onClose} size="md"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!toBranch || m.isPending} onClick={() => { setErr(null); m.mutate(); }}>Transfer</Button></>}>
      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="space-y-3">
        <ModalField label="Destination branch *">
          <select className={INPUT} value={toBranch} onChange={(e) => { setToBranch(e.target.value); setToWh(""); }}>
            <option value="">Select…</option>
            {branches.filter((b) => b.id !== unit.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </ModalField>
        <ModalField label="Destination location (optional)">
          <select className={INPUT} value={toWh} onChange={(e) => setToWh(e.target.value)} disabled={!toBranch}>
            <option value="">—</option>
            {whOptions.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </ModalField>
        <ModalField label="Note">
          <input className={INPUT} value={note} onChange={(e) => setNote(e.target.value)} />
        </ModalField>
      </div>
    </Modal>
  );
}
