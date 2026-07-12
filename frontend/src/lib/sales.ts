// Sales & Distribution API: quotation -> sales order -> delivery -> invoice ->
// payment -> receipt, plus POS fast-sale.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export type PaymentMethod =
  | "cash" | "card" | "mobile_money" | "bank_transfer" | "cheque" | "store_credit";

export const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "card", label: "Card" },
  { value: "mobile_money", label: "Mobile Money" },
  { value: "bank_transfer", label: "Bank Transfer" },
  { value: "cheque", label: "Cheque" },
  { value: "store_credit", label: "Store Credit" },
];

export interface PricedLineIn {
  product_id: string;
  qty: number;
  unit_price?: number | null;
  discount_pct?: number;
  tax_pct?: number;
  description?: string | null;
}

export interface PricedLineOut {
  id: string;
  product_id: string;
  sku: string | null;
  name: string | null;
  description: string | null;
  qty: number;
  unit_price: number;      // USD (source of truth)
  discount_pct: number;
  tax_pct: number;
  line_total: number;      // USD
  line_total_zmw: number;  // billed ZMW at the document's frozen rate
}

export interface SalesOrderLine extends PricedLineOut {
  reserved_qty: number;
  delivered_qty: number;
  outstanding_qty: number;
}

interface DocBase {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string | null;
  customer_address: string | null;
  customer_tax_number: string | null;
  branch_id: string | null;
  status: string;
  currency: string | null;
  subtotal: number;
  discount_total: number;
  net_total: number;
  tax_total: number;
  grand_total: number;
  vat_rate: number;
  created_at: string;
}

export interface Quotation extends DocBase {
  quote_number: string;
  valid_until: string | null;
  notes: string | null;
  fx_rate: number;           // USD -> ZMW rate frozen at quote creation
  grand_total_zmw: number;   // billed ZMW total
  lines: PricedLineOut[];
}

export interface SalesOrder extends DocBase {
  so_number: string;
  location_id: string | null;
  location_name: string | null;
  quotation_id: string | null;
  quote_number: string | null;
  payment_terms: string | null;
  delivery_terms: string | null;
  notes: string | null;
  lines: SalesOrderLine[];
}

export interface DeliveryNote {
  id: string;
  delivery_number: string;
  sales_order_id: string | null;
  so_number: string | null;
  customer_id: string;
  customer_name: string | null;
  location_id: string | null;
  location_name: string | null;
  status: string;
  received_by: string | null;
  delivered_at: string | null;
  created_at: string;
  lines: { id: string; product_id: string; sku: string | null; name: string | null; qty: number }[];
}

export interface Invoice extends DocBase {
  invoice_number: string;
  sales_order_id: string | null;
  delivery_note_id: string | null;
  invoice_date: string;
  due_date: string | null;
  payment_terms: string | null;
  fx_rate: number;           // USD -> ZMW rate frozen at issue
  grand_total_zmw: number;   // the PAYABLE (ZMW)
  amount_paid: number;       // ZMW
  balance: number;           // ZMW
  lines: PricedLineOut[];
}

export interface Receipt {
  id: string;
  receipt_number: string;
  invoice_id: string | null;
  invoice_number: string | null;
  customer_id: string | null;
  customer_name: string | null;
  amount_paid: number;
  balance: number;
  methods: { id: string; payment_number: string; method: string; amount: number }[];
  created_at: string;
}

export interface PaymentLineIn {
  method: PaymentMethod;
  amount: number;
  reference?: string | null;
}

export interface Payment {
  id: string;
  payment_number: string;
  method: string;
  amount: number;
  reference: string | null;
  received_by_name: string | null;
  created_at: string;
}

export interface PosResult {
  sales_order: SalesOrder;
  delivery_note: DeliveryNote;
  invoice: Invoice;
  receipt: Receipt;
}

export interface BikeSaleResult {
  unit_id: string;
  chassis_number: string;
  model_name: string | null;
  invoice: Invoice;
  receipt: Receipt | null;
}

export const RETURN_REASONS: { value: string; label: string }[] = [
  { value: "damaged", label: "Damaged" },
  { value: "wrong_item", label: "Wrong Item" },
  { value: "warranty", label: "Warranty" },
  { value: "changed_mind", label: "Customer Changed Mind" },
  { value: "other", label: "Other" },
];

export interface ReturnDoc {
  id: string;
  return_number: string;
  invoice_id: string | null;
  invoice_number: string | null;
  customer_id: string;
  customer_name: string | null;
  location_id: string | null;
  location_name: string | null;
  reason: string;
  status: string;
  created_at: string;
  lines: { id: string; product_id: string; sku: string | null; name: string | null; qty: number; reason: string | null }[];
}

export interface CreditNote extends DocBase {
  credit_note_number: string;
  invoice_id: string | null;
  invoice_number: string | null;
  return_id: string | null;
  applied_at: string | null;
  lines: PricedLineOut[];
}

export interface ReturnLineIn {
  product_id: string;
  qty: number;
  invoice_line_id?: string | null;
}

// One invoiced spare-part line — the line-grain parts sales log (fungible products
// only; motorcycle-linked invoices are excluded server-side).
export interface PartsSale {
  invoice_line_id: string;
  invoice_id: string;
  invoice_number: string;
  invoice_status: string;
  sale_date: string;
  product_id: string;
  sku: string | null;
  name: string | null;
  qty: number;
  unit_price: number;
  line_total: number;
  branch_id: string | null;
  branch_name: string | null;
  customer_id: string;
  customer_name: string | null;
}

export interface PartsSalesParams {
  branch_id?: string;
  product_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export interface MotoSale {
  unit_id: string;
  chassis_number: string;
  model_name: string | null;
  colour_name: string | null;
  sale_date: string | null;
  customer_name: string | null;
  revenue: number;
  invoice_id: string | null;
  invoice_number: string | null;
  historical: boolean;
}

async function downloadPdf(path: string, filename: string): Promise<void> {
  const token = tokenStore.getAccess();
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`PDF download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filename}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const salesApi = {
  // quotations
  listQuotations: (status = "") =>
    api.get<Quotation[]>(`/sales/quotations${status ? `?status=${status}` : ""}`),
  getQuotation: (id: string) => api.get<Quotation>(`/sales/quotations/${id}`),
  createQuotation: (body: { customer_id: string; branch_id?: string | null; notes?: string | null; lines: PricedLineIn[] }) =>
    api.post<Quotation>("/sales/quotations", body),
  sendQuotation: (id: string) => api.post<Quotation>(`/sales/quotations/${id}/send`),
  convertQuotation: (id: string, location_id: string) =>
    api.post<SalesOrder>(`/sales/quotations/${id}/convert`, { location_id }),

  // sales orders
  listOrders: (status = "") => api.get<SalesOrder[]>(`/sales/orders${status ? `?status=${status}` : ""}`),
  getOrder: (id: string) => api.get<SalesOrder>(`/sales/orders/${id}`),
  createOrder: (body: { customer_id: string; location_id: string; branch_id?: string | null; notes?: string | null; lines: PricedLineIn[] }) =>
    api.post<SalesOrder>("/sales/orders", body),
  confirmOrder: (id: string) => api.post<SalesOrder>(`/sales/orders/${id}/confirm`),
  cancelOrder: (id: string, reason?: string) =>
    api.post<SalesOrder>(`/sales/orders/${id}/cancel`, { reason: reason ?? null }),
  deliverOrder: (id: string) => api.post<DeliveryNote>(`/sales/orders/${id}/deliver`, { lines: [] }),

  // invoices
  listInvoices: (status = "") => api.get<Invoice[]>(`/sales/invoices${status ? `?status=${status}` : ""}`),
  getInvoice: (id: string) => api.get<Invoice>(`/sales/invoices/${id}`),
  createInvoice: (body: { sales_order_id?: string; delivery_note_id?: string }) =>
    api.post<Invoice>("/sales/invoices", body),

  // payment + receipt
  pay: (invoice_id: string, payments: PaymentLineIn[]) =>
    api.post<Receipt>("/sales/payments", { invoice_id, payments }),
  listInvoicePayments: (invoice_id: string) =>
    api.get<Payment[]>(`/sales/invoices/${invoice_id}/payments`),
  invoicesForCustomer: (customer_id: string) =>
    api.get<Invoice[]>(`/sales/invoices?customer_id=${customer_id}`),

  downloadInvoicePdf: (id: string, invoiceNumber: string) =>
    downloadPdf(`/sales/invoices/${id}/pdf`, invoiceNumber),
  downloadQuotationPdf: (id: string, quoteNumber: string) =>
    downloadPdf(`/sales/quotations/${id}/pdf`, quoteNumber),

  // POS
  posCheckout: (body: { location_id: string; customer_id?: string | null; lines: PricedLineIn[]; payments: PaymentLineIn[] }) =>
    api.post<PosResult>("/sales/pos/checkout", body),

  // sell a serialized bike (POS or Sales): bike invoice + mark sold + optional payment
  sellBike: (body: {
    unit_id: string;
    customer_id?: string | null;
    branch_id?: string | null;
    price?: number | null;
    payments?: PaymentLineIn[];
    note?: string | null;
  }) => api.post<BikeSaleResult>("/sales/bike-sale", body),

  // parts sales log (line-grain; fungible products only)
  listPartsSales: (params: PartsSalesParams = {}) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") sp.set(k, String(v));
    }
    const q = sp.toString();
    return api.get<PartsSale[]>(`/sales/parts-sales${q ? `?${q}` : ""}`);
  },

  // motorcycle sales log (line-grain; one row per sold unit)
  listMotorcycleSales: (params: { branch_id?: string; date_from?: string; date_to?: string; limit?: number } = {}) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") sp.set(k, String(v));
    }
    const q = sp.toString();
    return api.get<MotoSale[]>(`/sales/motorcycle-sales${q ? `?${q}` : ""}`);
  },

  // returns + credit notes
  listReturns: () => api.get<ReturnDoc[]>("/sales/returns"),
  createReturn: (body: { invoice_id: string; location_id: string; reason: string; lines: ReturnLineIn[] }) =>
    api.post<ReturnDoc>("/sales/returns", body),
  listCreditNotes: () => api.get<CreditNote[]>("/sales/credit-notes"),
  createCreditNote: (return_id: string) => api.post<CreditNote>("/sales/credit-notes", { return_id }),
  creditNoteAction: (id: string, action: "approve" | "apply" | "cancel") =>
    api.post<CreditNote>(`/sales/credit-notes/${id}/${action}`),
};
