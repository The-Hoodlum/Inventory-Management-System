// Order-request (branch requisition) API calls, on the shared request layer.
import { api } from "@/lib/api";
import type { InventoryRow, Page } from "@/types/api";

export type RequestStatus =
  | "pending"
  | "approved"
  | "partially_approved"
  | "rejected"
  | "issued"
  | "cancelled"
  | "completed";

export const PURPOSES: { value: string; label: string }[] = [
  { value: "for_sale", label: "Sale Fulfilment" },
  { value: "shelf_replenishment", label: "Shelf Replenishment" },
  { value: "branch_transfer", label: "Branch Transfer" },
  { value: "workshop_use", label: "Workshop Consumption" },
  { value: "stock_adjustment", label: "Stock Adjustment" },
  { value: "office_use", label: "Office Use" },
  { value: "other", label: "Other" },
];

export interface OrderRequestLine {
  id: string;
  product_id: string;
  sku: string | null;
  name: string | null;
  requested_qty: number;
  approved_qty: number;
  issued_qty: number;
  outstanding_qty: number;
  received_qty: number | null;
  missing_qty: number | null;
  damaged_qty: number | null;
  remarks: string | null;
}

export interface OrderRequest {
  id: string;
  request_number: string;
  branch_id: string;
  branch_name: string | null;
  requested_by: string | null;
  requester_name: string | null;
  purpose: string;
  status: RequestStatus;
  requested_date: string;
  approved_by: string | null;
  approved_date: string | null;
  issued_by: string | null;
  issued_date: string | null;
  completed_by: string | null;
  completer_name: string | null;
  completed_date: string | null;
  completion_remarks: string | null;
  comments: string | null;
  lines: OrderRequestLine[];
}

export interface AuditEntry {
  action: string;
  old_status: string | null;
  new_status: string | null;
  user_id: string | null;
  created_at: string;
}

export interface AdminDashboard {
  scope: "admin";
  pending: number;
  approved: number;
  rejected: number;
  issued: number;
  completed: number;
  cancelled: number;
  issued_today: number;
  requests_by_branch: { branch: string; count: number }[];
  most_requested_items: { sku: string; name: string; total_requested: number }[];
}

export interface BranchDashboard {
  scope: "branch";
  my_pending: number;
  my_approved: number;
  my_rejected: number;
  my_completed: number;
  my_recent_issued: string[];
}

export type Dashboard = AdminDashboard | BranchDashboard;

export interface ListParams {
  status?: string;
  purpose?: string;
  branch_id?: string;
  product_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export interface LineCreateInput {
  product_id: string;
  requested_qty: number;
  remarks?: string | null;
}

export interface CreateInput {
  branch_id: string;
  purpose: string;
  comments?: string | null;
  lines: LineCreateInput[];
}

export interface LineApprovalInput {
  line_id: string;
  approved_qty: number;
}

export interface LineReceiptInput {
  line_id: string;
  received_qty?: number | null;
  missing_qty?: number | null;
  damaged_qty?: number | null;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const orderRequestsApi = {
  list: (params: ListParams = {}) =>
    api.get<OrderRequest[]>(`/order-requests${qs(params as Record<string, string | number | undefined>)}`),
  get: (id: string) => api.get<OrderRequest>(`/order-requests/${id}`),
  audit: (id: string) => api.get<AuditEntry[]>(`/order-requests/${id}/audit`),
  dashboard: () => api.get<Dashboard>("/order-requests/dashboard"),
  create: (body: CreateInput) => api.post<OrderRequest>("/order-requests", body),
  approve: (id: string, lines: LineApprovalInput[], comments?: string) =>
    api.post<OrderRequest>(`/order-requests/${id}/approve`, { lines, comments: comments ?? null }),
  reject: (id: string, reason: string) =>
    api.post<OrderRequest>(`/order-requests/${id}/reject`, { reason }),
  issue: (id: string) => api.post<OrderRequest>(`/order-requests/${id}/issue`),
  cancel: (id: string, reason?: string) =>
    api.post<OrderRequest>(`/order-requests/${id}/cancel`, { reason: reason ?? null }),
  complete: (id: string, remarks: string, lines: LineReceiptInput[] = []) =>
    api.post<OrderRequest>(`/order-requests/${id}/complete`, { remarks, lines }),
};

/** Available-qty by product for a branch — powers the "search inventory" picker.
 * Best-effort hint: pages through up to a few hundred lines (the endpoint caps page_size
 * at 200); for very large branches not every line is preloaded. */
export async function branchAvailability(warehouseId: string): Promise<Map<string, number>> {
  const map = new Map<string, number>();
  for (let page = 1; page <= 3; page += 1) {
    const res = await api.get<Page<InventoryRow>>(
      `/inventory?warehouse_id=${warehouseId}&page=${page}&page_size=200`
    );
    for (const r of res.items) map.set(r.product_id, Number(r.qty_available));
    if (res.items.length < 200 || map.size >= res.total) break;
  }
  return map;
}
