// Shared split-payment editor: one or more payment lines (method + amount + optional
// reference) that sum toward an amount owed. Used by the Sales invoice pay modal, the Bike
// POS sell panel, and the Pending Payments page so every "how did they pay" surface behaves
// identically. Controlled: the parent owns the rows array; helpers below turn rows into the
// PaymentLineIn[] the API expects.
import { PAYMENT_METHODS, type PaymentLineIn, type PaymentMethod } from "@/lib/sales";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

export interface PaymentRow {
  method: PaymentMethod;
  amount: string;
  reference: string;
}

export const emptyPaymentRow = (method: PaymentMethod = "cash"): PaymentRow => ({
  method,
  amount: "",
  reference: "",
});

/** Sum of the entered amounts (blank/invalid rows count as 0). */
export function paymentRowsTotal(rows: PaymentRow[]): number {
  return rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
}

/** Rows with a positive amount, mapped to the API's PaymentLineIn shape. */
export function toPaymentLines(rows: PaymentRow[]): PaymentLineIn[] {
  return rows
    .filter((r) => Number(r.amount) > 0)
    .map((r) => ({ method: r.method, amount: Number(r.amount), reference: r.reference.trim() || null }));
}

export function PaymentRows({
  rows,
  onChange,
  fillAmount,
  fillLabel = "Pay full",
}: {
  rows: PaymentRow[];
  onChange: (rows: PaymentRow[]) => void;
  /** When given, shows a button that sets the first row's amount to this value. */
  fillAmount?: number;
  fillLabel?: string;
}) {
  const update = (i: number, patch: Partial<PaymentRow>) =>
    onChange(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const add = () => onChange([...rows, emptyPaymentRow("card")]);
  const remove = (i: number) => onChange(rows.filter((_, j) => j !== i));

  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr_1.2fr] gap-2">
          <select
            value={r.method}
            onChange={(e) => update(i, { method: e.target.value as PaymentMethod })}
            className={INPUT}
          >
            {PAYMENT_METHODS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <input
            type="number"
            min={0}
            value={r.amount}
            placeholder="Amount"
            onChange={(e) => update(i, { amount: e.target.value })}
            className={`${INPUT} text-right`}
          />
          <div className="flex items-center gap-1">
            <input
              value={r.reference}
              placeholder="Reference (txn / cheque no.)"
              onChange={(e) => update(i, { reference: e.target.value })}
              className={`${INPUT} min-w-0 flex-1`}
            />
            {rows.length > 1 && (
              <button
                type="button"
                onClick={() => remove(i)}
                aria-label="Remove payment line"
                className="shrink-0 px-1 text-slate-400 hover:text-red-600"
              >
                ×
              </button>
            )}
          </div>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <button type="button" onClick={add} className="text-xs text-brand-600 hover:underline">
          + Split payment
        </button>
        {fillAmount !== undefined && (
          <button
            type="button"
            onClick={() => update(0, { amount: String(fillAmount) })}
            className="text-xs text-slate-500 hover:underline"
          >
            {fillLabel}
          </button>
        )}
      </div>
    </div>
  );
}
