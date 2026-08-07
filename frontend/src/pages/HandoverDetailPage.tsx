// Customer Handover detail: the full signed form. A DRAFT is editable (customer snapshot,
// delivery facts, pre-delivery checklist, training, accessories, payment, 5-role approval,
// signatures) and can be saved or completed; a COMPLETED handover is read-only. Completing
// validates server-side (payment settled, QC + manager signed, customer signed, delivery
// dated), marks the bike delivered and starts its warranty. Both copies print to PDF.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Printer } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import {
  ACCESSORY_FIELDS,
  APPROVAL_ROLES,
  CHECKLIST_FIELDS,
  FUEL_LABELS,
  type FuelLevel,
  type Handover,
  type HandoverPatch,
  handoversApi,
  ROLE_LABELS,
  TRAINING_FIELDS,
} from "@/lib/handovers";

const INPUT =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:bg-slate-50 disabled:text-slate-500";

type Form = Record<string, unknown>;

const EDITABLE_TEXT = [
  "full_name", "nrc_passport_no", "phone", "whatsapp", "email", "physical_address",
  "checklist_remarks", "training_remarks", "other_items", "internal_remarks",
  "customer_signature_name", "salesperson_signature_name",
] as const;
const EDITABLE_BOOL = [
  ...CHECKLIST_FIELDS.map(([f]) => f),
  ...TRAINING_FIELDS.map(([f]) => f),
  ...ACCESSORY_FIELDS.map(([f]) => f),
];

function seedForm(h: Handover): Form {
  const f: Form = {};
  for (const k of EDITABLE_TEXT) f[k] = (h[k] as string) ?? "";
  for (const k of EDITABLE_BOOL) f[k] = Boolean(h[k]);
  f.delivery_date = h.delivery_date ?? "";
  f.warranty_start_date = h.warranty_start_date ?? "";
  f.odometer_reading_km = h.odometer_reading_km ?? "";
  f.fuel_level_at_delivery = h.fuel_level_at_delivery ?? "";
  f.payment_method = h.payment_method ?? "Cash";
  f.invoice_amount_zmw = h.invoice_amount_zmw ?? 0;
  f.amount_paid_zmw = h.amount_paid_zmw ?? 0;
  for (const role of APPROVAL_ROLES) {
    const ap = h.approvals.find((a) => a.role === role);
    f[`${role}_name`] = ap?.name ?? "";
    f[`${role}_signed`] = Boolean(ap?.signed);
  }
  return f;
}

function balanceOf(f: Form): number {
  return Number(f.invoice_amount_zmw || 0) - Number(f.amount_paid_zmw || 0);
}

function toPayload(f: Form): HandoverPatch {
  const p: HandoverPatch = { ...f };
  // Coerce the optional numerics: empty string -> null.
  p.odometer_reading_km = f.odometer_reading_km === "" ? null : Number(f.odometer_reading_km);
  p.amount_paid_zmw = Number(f.amount_paid_zmw || 0);
  p.invoice_amount_zmw = Number(f.invoice_amount_zmw || 0);
  p.balance_zmw = balanceOf(f);
  p.delivery_date = f.delivery_date || null;
  p.warranty_start_date = f.warranty_start_date || null;
  p.fuel_level_at_delivery = f.fuel_level_at_delivery || null;
  return p;
}

export default function HandoverDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("motorcycle.manage");
  const [form, setForm] = useState<Form | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);
  const [savedNote, setSavedNote] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["handover", id],
    queryFn: () => handoversApi.get(id),
  });

  useEffect(() => {
    if (data && form === null) setForm(seedForm(data));
  }, [data, form]);

  const readOnly = !canManage || data?.status === "COMPLETED";

  const save = useMutation({
    mutationFn: () => handoversApi.update(id, toPayload(form!)),
    onSuccess: (h) => {
      void qc.invalidateQueries({ queryKey: ["handovers"] });
      qc.setQueryData(["handover", id], h);
      setForm(seedForm(h));
      setErr(null);
      setSavedNote(true);
      setTimeout(() => setSavedNote(false), 2000);
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save."),
  });

  const complete = useMutation({
    mutationFn: () => handoversApi.complete(id, toPayload(form!)),
    onSuccess: (h) => {
      void qc.invalidateQueries({ queryKey: ["handovers"] });
      qc.setQueryData(["handover", id], h);
      setForm(seedForm(h));
      setErr(null);
      setReasons([]);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.details && typeof e.details === "object" && "reasons" in e.details) {
        setReasons((e.details as { reasons: string[] }).reasons);
        setErr("This handover isn't ready to complete.");
      } else {
        setErr(e instanceof ApiError ? e.message : "Could not complete.");
      }
    },
  });

  const print = useMutation({
    mutationFn: (copy: "customer" | "internal" | "both") => handoversApi.downloadPdf(id, data!.handover_no, copy),
    onError: () => setErr("Could not generate the PDF."),
  });

  if (isLoading || !data || !form) {
    return <div className="flex h-64 items-center justify-center"><Spinner label="Loading handover…" /></div>;
  }

  const set = (k: string, v: unknown) => setForm((f) => ({ ...(f as Form), [k]: v }));

  return (
    <div>
      <button onClick={() => navigate("/handovers")} className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="h-4 w-4" /> Handovers
      </button>

      <PageHeader
        title={data.handover_no}
        description={[data.model_name, data.colour_name, data.chassis_number].filter(Boolean).join(" · ")}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.status.toLowerCase()} />
            <Button variant="secondary" disabled={print.isPending} onClick={() => print.mutate("customer")}>
              <Printer className="h-4 w-4" /> Customer copy
            </Button>
            <Button variant="secondary" disabled={print.isPending} onClick={() => print.mutate("internal")}>
              <Printer className="h-4 w-4" /> Internal copy
            </Button>
            {!readOnly && (
              <>
                <Button variant="secondary" disabled={save.isPending} onClick={() => { setErr(null); save.mutate(); }}>
                  {save.isPending ? "Saving…" : savedNote ? "Saved ✓" : "Save draft"}
                </Button>
                <Button disabled={complete.isPending} onClick={() => { setErr(null); complete.mutate(); }}>
                  <CheckCircle2 className="h-4 w-4" /> {complete.isPending ? "Completing…" : "Complete"}
                </Button>
              </>
            )}
          </div>
        }
      />

      {err && (
        <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
          {reasons.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-xs">
              {reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
        </div>
      )}
      {data.status === "COMPLETED" && (
        <div className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Completed on {data.completed_at ? new Date(data.completed_at).toLocaleString() : "—"}. The bike is marked delivered and its warranty has started. This record is locked.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Motorcycle (read-only, pulled from the unit) */}
        <Section title="Motorcycle">
          <ReadRow label="Model" value={data.model_name} />
          <ReadRow label="Colour" value={data.colour_name} />
          <ReadRow label="Chassis / VIN" value={data.chassis_number} mono />
          <ReadRow label="Engine No." value={data.engine_number} mono />
          <ReadRow label="Invoice" value={data.invoice_number} />
          <ReadRow label="Branch" value={data.branch_name} />
          <ReadRow label="Salesperson" value={data.salesperson_display} />
        </Section>

        {/* Customer snapshot */}
        <Section title="Customer">
          <TextField label="Full name" value={form.full_name} onChange={(v) => set("full_name", v)} disabled={readOnly} />
          <TextField label="NRC / Passport" value={form.nrc_passport_no} onChange={(v) => set("nrc_passport_no", v)} disabled={readOnly} />
          <div className="grid grid-cols-2 gap-2">
            <TextField label="Phone" value={form.phone} onChange={(v) => set("phone", v)} disabled={readOnly} />
            <TextField label="WhatsApp" value={form.whatsapp} onChange={(v) => set("whatsapp", v)} disabled={readOnly} />
          </div>
          <TextField label="Email" value={form.email} onChange={(v) => set("email", v)} disabled={readOnly} />
          <TextField label="Physical address" value={form.physical_address} onChange={(v) => set("physical_address", v)} disabled={readOnly} />
        </Section>

        {/* Delivery facts */}
        <Section title="Delivery">
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Delivery date</span>
              <input type="date" className={INPUT} disabled={readOnly} value={String(form.delivery_date ?? "")} onChange={(e) => set("delivery_date", e.target.value)} />
            </label>
            <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Warranty start</span>
              <input type="date" className={INPUT} disabled={readOnly} value={String(form.warranty_start_date ?? "")} onChange={(e) => set("warranty_start_date", e.target.value)} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Odometer (km)</span>
              <input type="number" min={0} className={INPUT} disabled={readOnly} value={String(form.odometer_reading_km ?? "")} onChange={(e) => set("odometer_reading_km", e.target.value)} />
            </label>
            <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Fuel at delivery</span>
              <select className={INPUT} disabled={readOnly} value={String(form.fuel_level_at_delivery ?? "")} onChange={(e) => set("fuel_level_at_delivery", e.target.value)}>
                <option value="">—</option>
                {(["E", "1", "2", "3", "F"] as FuelLevel[]).map((lv) => <option key={lv} value={lv}>{FUEL_LABELS[lv]}</option>)}
              </select>
            </label>
          </div>
        </Section>

        {/* Payment */}
        <Section title="Payment">
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">Method</span>
            <select className={INPUT} disabled={readOnly} value={String(form.payment_method ?? "Cash")} onChange={(e) => set("payment_method", e.target.value)}>
              {["Cash", "Bank Transfer", "Airtel Money", "Other"].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-3 gap-2">
            <NumField label="Invoice (ZMW)" value={form.invoice_amount_zmw} onChange={(v) => set("invoice_amount_zmw", v)} disabled={readOnly} />
            <NumField label="Paid (ZMW)" value={form.amount_paid_zmw} onChange={(v) => set("amount_paid_zmw", v)} disabled={readOnly} />
            <div className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Balance</span>
              <div className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${balanceOf(form) > 0 ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
                {formatNumber(balanceOf(form), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>
          </div>
          <TextArea label="Internal remarks" value={form.internal_remarks} onChange={(v) => set("internal_remarks", v)} disabled={readOnly} />
        </Section>

        {/* Checklist */}
        <Section title="Pre-delivery checklist" wide>
          <CheckGrid fields={CHECKLIST_FIELDS} form={form} set={set} disabled={readOnly} />
          <TextArea label="Checklist remarks" value={form.checklist_remarks} onChange={(v) => set("checklist_remarks", v)} disabled={readOnly} />
        </Section>

        {/* Training */}
        <Section title="Customer training">
          <CheckGrid fields={TRAINING_FIELDS} form={form} set={set} disabled={readOnly} />
          <TextArea label="Training remarks" value={form.training_remarks} onChange={(v) => set("training_remarks", v)} disabled={readOnly} />
        </Section>

        {/* Accessories */}
        <Section title="Items / accessories">
          <CheckGrid fields={ACCESSORY_FIELDS} form={form} set={set} disabled={readOnly} cols={3} />
          <TextField label="Other items" value={form.other_items} onChange={(v) => set("other_items", v)} disabled={readOnly} />
        </Section>

        {/* Approval grid */}
        <Section title="Verification & approval" wide>
          <div className="space-y-2">
            {APPROVAL_ROLES.map((role) => (
              <div key={role} className="grid grid-cols-[1fr_auto] items-center gap-3">
                <input
                  className={INPUT}
                  disabled={readOnly}
                  placeholder={ROLE_LABELS[role]}
                  value={String(form[`${role}_name`] ?? "")}
                  onChange={(e) => set(`${role}_name`, e.target.value)}
                />
                <label className="flex items-center gap-2 whitespace-nowrap text-sm text-slate-600">
                  <input type="checkbox" disabled={readOnly} checked={Boolean(form[`${role}_signed`])} onChange={(e) => set(`${role}_signed`, e.target.checked)} />
                  Signed
                </label>
              </div>
            ))}
          </div>
        </Section>

        {/* Signatures */}
        <Section title="Signatures">
          <TextField label="Customer signature (name)" value={form.customer_signature_name} onChange={(v) => set("customer_signature_name", v)} disabled={readOnly} />
          <TextField label="Salesperson signature (name)" value={form.salesperson_signature_name} onChange={(v) => set("salesperson_signature_name", v)} disabled={readOnly} />
          <p className="text-xs text-slate-400">First service reminder is printed on the customer copy: 500 KM or 30 days.</p>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children, wide }: { title: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <Card className={`p-4 ${wide ? "lg:col-span-2" : ""}`}>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="space-y-3">{children}</div>
    </Card>
  );
}

function ReadRow({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-2 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className={`font-medium text-slate-800 ${mono ? "font-mono text-[13px]" : ""}`}>{value || "—"}</span>
    </div>
  );
}

function TextField({ label, value, onChange, disabled }: { label: string; value: unknown; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input className={INPUT} disabled={disabled} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function NumField({ label, value, onChange, disabled }: { label: string; value: unknown; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input type="number" min={0} step="0.01" className={INPUT} disabled={disabled} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function TextArea({ label, value, onChange, disabled }: { label: string; value: unknown; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <textarea className={`${INPUT} min-h-[52px]`} disabled={disabled} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function CheckGrid({ fields, form, set, disabled, cols = 2 }: {
  fields: [string, string][];
  form: Form;
  set: (k: string, v: unknown) => void;
  disabled?: boolean;
  cols?: number;
}) {
  return (
    <div className={`grid gap-x-4 gap-y-1.5 ${cols === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
      {fields.map(([field, label]) => (
        <label key={field} className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" disabled={disabled} checked={Boolean(form[field])} onChange={(e) => set(field, e.target.checked)} />
          {label}
        </label>
      ))}
    </div>
  );
}
