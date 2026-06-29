// Sales & Distribution API: quotation -> sales order -> delivery -> invoice ->
// payment -> receipt, plus POS fast-sale.
import { api } from "@/lib/api";

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
  unit_price: number;
  discount_pct: number;
  tax_pct: number;
  line_total: number;
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
  branch_id: string | null;
  status: string;
  currency: string | null;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  grand_total: number;
  created_at: string;
}

export interface Quotation extends DocBase {
  quote_number: string;
  valid_until: string | null;
  notes: string | null;
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
  amount_paid: number;
  balance: number;
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

export interface PosResult {
  sales_order: SalesOrder;
  delivery_note: DeliveryNote;
  invoice: Invoice;
  receipt: Receipt;
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

  // POS
  posCheckout: (body: { location_id: string; customer_id?: string | null; lines: PricedLineIn[]; payments: PaymentLineIn[] }) =>
    api.post<PosResult>("/sales/pos/checkout", body),
};
