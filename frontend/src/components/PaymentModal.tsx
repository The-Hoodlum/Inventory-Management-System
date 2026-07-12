// Record a payment against an invoice: shows the ZMW payable + outstanding balance and any
// prior payments, then takes one or more split-payment lines (shared PaymentRows) that must
// not exceed the balance. Used by the Sales page and the Pending Payments (AR) page. On
// success it invalidates the ["sales", ...] query tree, so any list keyed under "sales"
// (invoices, outstanding) refreshes automatically.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "@/components/Modal";
import { emptyPaymentRow, type PaymentRow, PaymentRows, paymentRowsTotal, toPaymentLines } from "@/components/PaymentRows";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatMoney, formatNumber, titleCase } from "@/lib/format";
import { salesApi } from "@/lib/sales";

export function PaymentModal({ invoiceId, onClose }: { invoiceId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: inv } = useQuery({ queryKey: ["sales", "invoice", invoiceId], queryFn: () => salesApi.getInvoice(invoiceId) });
  const priorPayments = useQuery({ queryKey: ["sales", "invoice-payments", invoiceId], queryFn: () => salesApi.listInvoicePayments(invoiceId) });
  const [rows, setRows] = useState<PaymentRow[]>([emptyPaymentRow("cash")]);
  const [err, setErr] = useState<string | null>(null);
  const balance = inv?.balance ?? 0;
  const entered = paymentRowsTotal(rows);

  const pay = useMutation({
    mutationFn: () => salesApi.pay(invoiceId, toPaymentLines(rows)),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["sales"] }); onClose(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Payment failed."),
  });

  return (
    <Modal title={inv ? `Pay ${inv.invoice_number}` : "Record payment"} size="md" onClose={onClose} footer={
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={entered <= 0 || entered > balance + 0.001 || pay.isPending}
          onClick={() => { setErr(null); pay.mutate(); }}>
          {pay.isPending ? "Recording…" : "Record payment"}</Button>
      </>
    }>
      <div className="space-y-3">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        {inv && (
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
            <div className="flex justify-between text-slate-500">
              <span>USD total</span><span className="font-mono">{formatMoney(inv.grand_total)}</span></div>
            <div className="flex justify-between text-slate-500">
              <span>Rate</span><span className="font-mono">{formatNumber(inv.fx_rate)}</span></div>
            <div className="flex justify-between font-medium text-slate-700">
              <span>ZMW payable</span><span className="font-mono">{formatMoney(inv.grand_total_zmw, "ZMW")}</span></div>
          </div>
        )}
        <div className="flex justify-between text-sm"><span className="text-slate-500">Outstanding balance (ZMW)</span>
          <span className="font-mono font-semibold">{formatMoney(balance, "ZMW")}</span></div>

        {(priorPayments.data?.length ?? 0) > 0 && (
          <div className="rounded-lg border border-slate-200 text-xs">
            <div className="border-b border-slate-100 px-3 py-1.5 font-medium text-slate-500">Payments so far</div>
            {(priorPayments.data ?? []).map((p) => (
              <div key={p.id} className="flex items-center justify-between px-3 py-1.5">
                <span className="text-slate-600">
                  {titleCase(p.method.replace("_", " "))}
                  {p.reference ? <span className="ml-1 text-slate-400">· {p.reference}</span> : null}
                  {p.received_by_name ? <span className="ml-1 text-slate-400">· by {p.received_by_name}</span> : null}
                </span>
                <span className="font-mono text-slate-700">{formatMoney(p.amount, "ZMW")}</span>
              </div>
            ))}
          </div>
        )}

        <PaymentRows rows={rows} onChange={setRows} fillAmount={balance} />
        {entered > balance + 0.001 && <div className="text-sm text-red-600">Exceeds the outstanding balance.</div>}
      </div>
    </Modal>
  );
}
