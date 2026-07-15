// Branch -> customer/reseller delivery (Type 3) API. A delivery note is PAPER: it never
// mutates stock itself. sale mode is proof of a handover the sale already deducted for;
// consignment mode holds parts / consigns bikes on deliver, then settle deducts the sold
// portion and return releases the unsold hold.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export type CustomerDeliveryMode = "sale" | "consignment";
export type CustomerDeliveryStatus =
  | "draft"
  | "delivered"
  | "out_at_reseller"
  | "partially_settled"
  | "settled"
  | "returned"
  | "cancelled";

export function deliveryStatusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const OPEN_CONSIGNMENT: CustomerDeliveryStatus[] = ["out_at_reseller", "partially_settled"];

export interface CustomerDeliveryLine {
  id: string;
  line_kind: "motorcycle" | "part";
  product_id: string | null;
  sku: string | null;
  name: string | null;
  unit_id: string | null;
  chassis_number: string | null;
  engine_number: string | null;
  model_name: string | null;
  assembly_pending: boolean;   // bike sold before assembly — dispatch is blocked without a manager override
  qty: number;
  settled_qty: number;
  returned_qty: number;
  sold_invoice_id: string | null;
  remarks: string | null;
}

export interface CustomerDelivery {
  id: string;
  delivery_number: string;
  delivery_mode: CustomerDeliveryMode;
  status: CustomerDeliveryStatus;
  branch_id: string | null;
  branch_name: string | null;
  from_warehouse_id: string;
  from_warehouse_name: string | null;
  customer_id: string;
  customer_name: string | null;
  invoice_id: string | null;
  invoice_number: string | null;
  remarks: string | null;
  dispatched_at: string | null;
  received_by: string | null;
  received_at: string | null;
  created_at: string;
  lines: CustomerDeliveryLine[];
}

export interface CreateCustomerDeliveryBody {
  delivery_mode: CustomerDeliveryMode;
  from_warehouse_id: string;
  customer_id?: string | null;
  invoice_id?: string | null;
  remarks?: string;
  part_lines?: { product_id: string; qty: number }[];
  bike_lines?: { unit_id: string }[];
}

export interface SettleCustomerDeliveryBody {
  remarks?: string;
  part_lines?: { line_id: string; settled_qty?: number; returned_qty?: number }[];
  bike_lines?: { line_id: string; outcome: "sold" | "returned"; invoice_id?: string | null }[];
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const customerDeliveryApi = {
  list: (params: { customer_id?: string; status?: string; mode?: string } = {}) =>
    api.get<CustomerDelivery[]>(`/customer-deliveries${qs(params)}`),
  get: (id: string) => api.get<CustomerDelivery>(`/customer-deliveries/${id}`),
  create: (body: CreateCustomerDeliveryBody) => api.post<CustomerDelivery>("/customer-deliveries", body),
  deliver: (id: string, opts: { received_by?: string | null; override_unassembled?: boolean } = {}) =>
    api.post<CustomerDelivery>(`/customer-deliveries/${id}/deliver`, {
      received_by: opts.received_by ?? null,
      override_unassembled: opts.override_unassembled ?? false,
    }),
  settle: (id: string, body: SettleCustomerDeliveryBody) =>
    api.post<CustomerDelivery>(`/customer-deliveries/${id}/settle`, body),
  cancel: (id: string, reason?: string) =>
    api.post<CustomerDelivery>(`/customer-deliveries/${id}/cancel`, { reason: reason ?? null }),

  async downloadPdf(id: string, deliveryNumber: string): Promise<void> {
    const token = tokenStore.getAccess();
    const res = await fetch(`${BASE_URL}/customer-deliveries/${id}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`PDF download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${deliveryNumber}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
