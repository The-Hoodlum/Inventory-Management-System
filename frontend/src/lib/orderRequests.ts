// Order-request (branch requisition) API calls, on the shared request layer.
import { api } from "@/lib/api";
import type { InventoryRow, Page } from "@/types/api";

export type RequestStatus =
  | "draft"
  | "pending"
  | "approved"
  | "partially_approved"
  | "rejected"
  | "partially_issued"
  | "issued"
  | "in_transit"
  | "partially_received"
  | "received"
  | "cancelled"
  | "completed";

// Transfer types (the request "purpose"). Industry-agnostic; the 8 spec types plus
// office_use for back-compat.
export const PURPOSES: { value: string; label: string }[] = [
  { value: "shelf_replenishment", label: "Shelf Replenishment" },
  { value: "internal_transfer", label: "Internal Transfer" },
  { value: "branch_transfer", label: "Branch Transfer" },
  { value: "for_sale", label: "Sale Fulfilment" },
  { value: "workshop_use", label: "Workshop Consumption" },
  { value: "damaged_replacement", label: "Damaged Replacement" },
  { value: "stock_adjustment", label: "Stock Adjustment" },
  { value: "office_use", label: "Office Use" },
  { value: "other", label: "Other" },
];

// Transfer types that move stock to a destination location (vs. consume at source).
export const TRANSFER_TYPES = new Set([
  "shelf_replenishment",
  "internal_transfer",
  "branch_transfer",
  "damaged_replacement",
]);

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
  extra_qty: number | null;
  variance: number;
  balanced: boolean;
  remarks: string | null;
}

export interface OrderRequest {
  id: string;
  request_number: string;
  transfer_type: string;
  purpose: string;
  status: RequestStatus;
  reason: string | null;
  branch_id: string;
  branch_name: string | null;
  destination_branch_id: string | null;
  destination_branch_name: string | null;
  source_location_id: string | null;
  source_location_name: string | null;
  source_branch_id: string | null;
  source_branch_name: string | null;
  dest_location_id: string | null;
  dest_location_name: string | null;
  dest_branch_id: string | null;
  dest_branch_name: string | null;
  requested_by: string | null;
  requester_name: string | null;
  requested_date: string;
  approved_by: string | null;
  approved_date: string | null;
  issued_by: string | null;
  issued_date: string | null;
  received_by: string | null;
  receiver_name: string | null;
  received_date: string | null;
  completed_by: string | null;
  completer_name: string | null;
  completed_date: string | null;
  completion_remarks: string | null;
  comments: string | null;
  lines: OrderRequestLine[];
}

/** Receipt variance for a line = (issued + extra) - (received + missing + damaged).
 * Zero means the line reconciles. */
export function lineVariance(l: {
  issued_qty: number;
  extra_qty?: number | null;
  received_qty?: number | null;
  missing_qty?: number | null;
  damaged_qty?: number | null;
}): number {
  return (
    (l.issued_qty + (l.extra_qty ?? 0)) -
    ((l.received_qty ?? 0) + (l.missing_qty ?? 0) + (l.damaged_qty ?? 0))
  );
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
  in_transit: number;
  received: number;
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
  source_location_id: string; // fulfil-from location
  destination_location_id?: string | null; // where stock is needed
  purpose: string; // transfer type
  comments?: string | null; // reason (required when a destination is set)
  submit?: boolean; // false => save as draft
  lines: LineCreateInput[];
}

export interface LineApprovalInput {
  line_id: string;
  approved_qty: number;
}

export interface LineIssueInput {
  line_id: string;
  issue_qty: number;
}

export interface LineReceiptInput {
  line_id: string;
  received_qty?: number | null;
  missing_qty?: number | null;
  damaged_qty?: number | null;
  extra_qty?: number | null;
}

export interface LedgerEntry {
  id: string;
  event: string;
  request_number: string;
  product_id: string;
  sku: string | null;
  name: string | null;
  qty_requested: number | null;
  qty_approved: number | null;
  qty_issued: number | null;
  qty_received: number | null;
  qty_missing: number | null;
  qty_damaged: number | null;
  qty_extra: number | null;
  source_branch_name: string | null;
  source_location_name: string | null;
  dest_branch_name: string | null;
  dest_location_name: string | null;
  transfer_type: string | null;
  reason: string | null;
  created_at: string;
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
  ledger: (id: string) => api.get<LedgerEntry[]>(`/order-requests/${id}/ledger`),
  dashboard: () => api.get<Dashboard>("/order-requests/dashboard"),
  create: (body: CreateInput) => api.post<OrderRequest>("/order-requests", body),
  submit: (id: string) => api.post<OrderRequest>(`/order-requests/${id}/submit`),
  approve: (id: string, lines: LineApprovalInput[], comments?: string) =>
    api.post<OrderRequest>(`/order-requests/${id}/approve`, { lines, comments: comments ?? null }),
  reject: (id: string, reason: string) =>
    api.post<OrderRequest>(`/order-requests/${id}/reject`, { reason }),
  issue: (id: string, lines: LineIssueInput[] = []) =>
    api.post<OrderRequest>(`/order-requests/${id}/issue`, { lines }),
  receive: (id: string, remarks: string, lines: LineReceiptInput[]) =>
    api.post<OrderRequest>(`/order-requests/${id}/receive`, { remarks, lines }),
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
