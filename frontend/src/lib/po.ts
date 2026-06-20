// Purchase-order API calls, built on the shared request layer.
import { api, BASE_URL, tokenStore } from "@/lib/api";
import type { POEvent, Page, PurchaseOrder, ReceiptResult } from "@/types/api";

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface ListParams {
  status?: string;
  supplier_id?: string;
  warehouse_id?: string;
  page?: number;
  page_size?: number;
}

export interface ReceiptLineInput {
  line_id: string;
  quantity: string;
}

export interface POLineCreateInput {
  product_id: string;
  ordered_qty: string;
  unit_cost: string;
  units_per_carton?: number | null;
  ordered_cartons?: number | null;
}

export interface POCreateInput {
  supplier_id: string;
  warehouse_id: string;
  currency?: string | null;
  fx_rate?: string | null;
  expected_date?: string | null;
  notes?: string | null;
  lines: POLineCreateInput[];
}

export const poApi = {
  list: (params: ListParams = {}) =>
    api.get<Page<PurchaseOrder>>(`/purchase-orders${qs(params as Record<string, string | number | undefined>)}`),
  get: (id: string) => api.get<PurchaseOrder>(`/purchase-orders/${id}`),
  events: (id: string) => api.get<POEvent[]>(`/purchase-orders/${id}/events`),

  create: (body: POCreateInput) => api.post<PurchaseOrder>("/purchase-orders", body),

  submit: (id: string, comment?: string) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/submit`, { comment: comment ?? null }),
  approve: (id: string, comment?: string) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/approve`, { comment: comment ?? null }),
  reject: (id: string, comment?: string) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/reject`, { comment: comment ?? null }),
  cancel: (id: string, comment?: string) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/cancel`, { comment: comment ?? null }),
  send: (id: string, comment?: string) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/send`, { comment: comment ?? null }),

  receive: (id: string, lines: ReceiptLineInput[], note?: string) =>
    api.post<ReceiptResult>(`/purchase-orders/${id}/receipts`, { lines, note: note ?? null }),
};

/** Fetch the PO PDF with the auth header and open it in a new tab. */
export async function openPurchaseOrderPdf(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/purchase-orders/${id}/pdf`, {
    headers: { Authorization: `Bearer ${tokenStore.getAccess() ?? ""}` },
  });
  if (!res.ok) throw new Error("Couldn't load the PDF.");
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
