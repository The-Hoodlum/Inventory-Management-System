// Typed delivery / dispatch notes API — paper that documents a stock movement.
// Type 1: warehouse -> branch transfer (dispatch -> in_transit -> receive, with
// per-line discrepancy). Parts move via InventoryService, bikes via the serialized
// registry; this client never touches stock directly.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export const DISPATCH_TYPES = [
  { value: "warehouse_branch_transfer", label: "Warehouse → Branch transfer" },
  { value: "branch_branch_transfer", label: "Branch → Branch transfer" },
] as const;
export type DispatchType = (typeof DISPATCH_TYPES)[number]["value"];
export type DispatchStatus = "draft" | "in_transit" | "partially_received" | "received" | "cancelled";

export function dispatchStatusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface DispatchLine {
  id: string;
  line_kind: "motorcycle" | "part";
  product_id: string | null;
  sku: string | null;
  name: string | null;
  unit_id: string | null;
  chassis_number: string | null;
  engine_number: string | null;
  model_name: string | null;
  dispatched_qty: number;
  received_qty: number;
  missing_qty: number;
  damaged_qty: number;
  remarks: string | null;
}

export interface DispatchNote {
  id: string;
  note_number: string;
  dispatch_type: DispatchType;
  status: DispatchStatus;
  from_branch_id: string | null;
  from_branch_name: string | null;
  from_warehouse_id: string;
  from_warehouse_name: string | null;
  to_branch_id: string | null;
  to_branch_name: string | null;
  to_warehouse_id: string;
  to_warehouse_name: string | null;
  remarks: string | null;
  dispatched_by: string | null;
  dispatched_at: string | null;
  received_by: string | null;
  received_at: string | null;
  created_at: string;
  lines: DispatchLine[];
}

export interface CreateNoteBody {
  dispatch_type?: DispatchType;
  from_warehouse_id: string;
  to_warehouse_id: string;
  remarks?: string | null;
  part_lines?: { product_id: string; qty: number; remarks?: string }[];
  bike_lines?: { unit_id: string; remarks?: string }[];
}

export interface ReceiveBody {
  received_by?: string | null;
  remarks?: string | null;
  part_lines?: { line_id: string; received_qty: number; damaged_qty?: number }[];
  bike_lines?: { line_id: string; received: boolean }[];
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const dispatchApi = {
  list: (params: { branch_id?: string; status?: string; type?: string } = {}) =>
    api.get<DispatchNote[]>(`/delivery-notes${qs(params)}`),
  get: (id: string) => api.get<DispatchNote>(`/delivery-notes/${id}`),
  create: (body: CreateNoteBody) => api.post<DispatchNote>("/delivery-notes", body),
  dispatch: (id: string) => api.post<DispatchNote>(`/delivery-notes/${id}/dispatch`),
  receive: (id: string, body: ReceiveBody) => api.post<DispatchNote>(`/delivery-notes/${id}/receive`, body),
  cancel: (id: string, reason?: string) =>
    api.post<DispatchNote>(`/delivery-notes/${id}/cancel`, { reason: reason ?? null }),

  async downloadPdf(id: string, noteNumber: string): Promise<void> {
    const token = tokenStore.getAccess();
    const res = await fetch(`${BASE_URL}/delivery-notes/${id}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`PDF download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${noteNumber}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
