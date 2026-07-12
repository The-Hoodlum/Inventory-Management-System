import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type Customer, type CustomerInput, customersApi, useCustomers } from "@/lib/customers";
import { formatDate, formatMoney } from "@/lib/format";
import { salesApi } from "@/lib/sales";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const TH = "px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-slate-500";
const TD = "px-4 py-3 text-slate-700";

export default function CustomersPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("customer.manage");
  const [search, setSearch] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [historyOf, setHistoryOf] = useState<Customer | null>(null);
  const list = useCustomers(search);

  return (
    <div>
      <PageHeader
        title="Customers"
        description="Customer master — contacts, credit terms and outstanding balances."
        actions={canManage ? (
          <Button onClick={() => setShowNew(true)}><Plus className="h-4 w-4" /> New customer</Button>
        ) : undefined}
      />

      <div className="mb-4">
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, code, phone or email" className={`${INPUT} w-full max-w-md`} />
      </div>

      {list.isLoading ? (
        <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
      ) : !list.data || list.data.items.length === 0 ? (
        <Card className="p-10 text-center text-sm text-slate-400">No customers yet.</Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="border-b border-slate-200">
                  <th className={TH}>Code</th>
                  <th className={TH}>Name</th>
                  <th className={TH}>Contact</th>
                  <th className={TH}>Phone</th>
                  <th className={`${TH} text-right`}>Credit limit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.items.map((c) => (
                  <tr key={c.id} onClick={() => setHistoryOf(c)} className="cursor-pointer hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-[13px] text-slate-700">{c.code}</td>
                    <td className={`${TD} font-medium`}>{c.name}</td>
                    <td className={`${TD} text-slate-600`}>{c.contact_name ?? "—"}</td>
                    <td className={`${TD} text-slate-600`}>{c.phone ?? "—"}</td>
                    <td className={`${TD} text-right font-mono`}>
                      {c.credit_limit > 0 ? formatMoney(c.credit_limit) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showNew && <NewCustomerModal onClose={() => setShowNew(false)} />}
      {historyOf && <CustomerHistoryModal customer={historyOf} onClose={() => setHistoryOf(null)} />}
    </div>
  );
}

function NewCustomerModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<CustomerInput>({ name: "", credit_limit: 0 });
  const [addr, setAddr] = useState("");
  const [city, setCity] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof CustomerInput, v: string | number) => setForm((f) => ({ ...f, [k]: v }));

  const create = useMutation({
    mutationFn: () => customersApi.create({
      ...form, phone: form.phone || null, email: form.email || null,
      tax_number: form.tax_number || null, payment_terms: form.payment_terms || null,
      addresses: addr.trim()
        ? [{ line1: addr.trim(), city: city.trim() || null, address_type: "billing", is_default: true }]
        : undefined,
    }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["customers"] }); onClose(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not create customer."),
  });

  return (
    <Modal title="New customer" size="md" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!form.name.trim() || create.isPending}
          onClick={() => { setErr(null); create.mutate(); }}>
          {create.isPending ? "Saving…" : "Create"}
        </Button>
      </>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <Field label="Name"><input className={`${INPUT} w-full`} value={form.name}
          onChange={(e) => set("name", e.target.value)} autoFocus /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Contact"><input className={`${INPUT} w-full`} value={form.contact_name ?? ""}
            onChange={(e) => set("contact_name", e.target.value)} /></Field>
          <Field label="Phone"><input className={`${INPUT} w-full`} value={form.phone ?? ""}
            onChange={(e) => set("phone", e.target.value)} /></Field>
          <Field label="Email"><input className={`${INPUT} w-full`} value={form.email ?? ""}
            onChange={(e) => set("email", e.target.value)} /></Field>
          <Field label="Tax number"><input className={`${INPUT} w-full`} value={form.tax_number ?? ""}
            onChange={(e) => set("tax_number", e.target.value)} /></Field>
          <Field label="Payment terms"><input className={`${INPUT} w-full`} value={form.payment_terms ?? ""}
            onChange={(e) => set("payment_terms", e.target.value)} placeholder="e.g. net_30" /></Field>
          <Field label="Credit limit"><input type="number" min={0} className={`${INPUT} w-full`}
            value={form.credit_limit ?? 0} onChange={(e) => set("credit_limit", Number(e.target.value))} /></Field>
        </div>
        <Field label="Address"><input className={`${INPUT} w-full`} value={addr}
          onChange={(e) => setAddr(e.target.value)} placeholder="Street / area (shown on invoices & quotations)" /></Field>
        <Field label="City / town"><input className={`${INPUT} w-full`} value={city}
          onChange={(e) => setCity(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}


// Purchase history: the customer's invoices (what they bought, when, how much) with
// paid / balance / status, each expandable to show HOW it was paid (split payment lines).
function CustomerHistoryModal({ customer, onClose }: { customer: Customer; onClose: () => void }) {
  const [openInvoice, setOpenInvoice] = useState<string | null>(null);
  const invoices = useQuery({
    queryKey: ["customer-invoices", customer.id],
    queryFn: () => salesApi.invoicesForCustomer(customer.id),
  });
  const addr = customer.addresses?.[0];
  const addrText = addr ? [addr.line1, addr.city, addr.country].filter(Boolean).join(", ") : null;

  return (
    <Modal title={`${customer.name} — history`} size="lg" onClose={onClose}
      footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm md:grid-cols-4">
          <Detail label="Phone" value={customer.phone} />
          <Detail label="Tax number" value={customer.tax_number} />
          <Detail label="Address" value={addrText} />
          <Detail label="Payment terms" value={customer.payment_terms} />
        </div>

        {invoices.isLoading ? (
          <div className="flex h-24 items-center justify-center"><Spinner label="Loading history…" /></div>
        ) : (invoices.data ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-400">No purchases yet.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-medium">Invoice</th>
                  <th className="px-3 py-2 font-medium">Date</th>
                  <th className="px-3 py-2 text-right font-medium">Total (ZMW)</th>
                  <th className="px-3 py-2 text-right font-medium">Paid</th>
                  <th className="px-3 py-2 text-right font-medium">Balance</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(invoices.data ?? []).map((inv) => (
                  <>
                    <tr key={inv.id} onClick={() => setOpenInvoice(openInvoice === inv.id ? null : inv.id)}
                      className="cursor-pointer hover:bg-slate-50">
                      <td className="px-3 py-2 font-mono text-xs text-slate-700">{inv.invoice_number}</td>
                      <td className="px-3 py-2 text-slate-600">{formatDate(inv.invoice_date)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatMoney(inv.grand_total_zmw, "ZMW")}</td>
                      <td className="px-3 py-2 text-right font-mono text-emerald-700">{formatMoney(inv.amount_paid, "ZMW")}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatMoney(inv.balance, "ZMW")}</td>
                      <td className="px-3 py-2"><StatusBadge status={inv.status} /></td>
                    </tr>
                    {openInvoice === inv.id && <InvoicePaymentsRow invoiceId={inv.id} />}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}

function InvoicePaymentsRow({ invoiceId }: { invoiceId: string }) {
  const payments = useQuery({
    queryKey: ["invoice-payments", invoiceId],
    queryFn: () => salesApi.listInvoicePayments(invoiceId),
  });
  return (
    <tr className="bg-slate-50/60">
      <td colSpan={6} className="px-4 py-2">
        {payments.isLoading ? (
          <Spinner label="Loading payments…" />
        ) : (payments.data ?? []).length === 0 ? (
          <span className="text-xs text-slate-400">No payments recorded on this invoice.</span>
        ) : (
          <div className="space-y-1">
            {(payments.data ?? []).map((p) => (
              <div key={p.id} className="flex items-center justify-between text-xs text-slate-600">
                <span>
                  {formatDate(p.created_at)} · {p.method.replace("_", " ")}
                  {p.reference ? ` · ${p.reference}` : ""}
                  {p.received_by_name ? ` · by ${p.received_by_name}` : ""}
                </span>
                <span className="font-mono">{formatMoney(p.amount, "ZMW")}</span>
              </div>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className="text-2xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-slate-700">{value || "—"}</div>
    </div>
  );
}
