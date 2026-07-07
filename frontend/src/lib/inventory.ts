// Inventory operations: stock adjustments, warehouse transfers, and the
// movement ledger — built on the shared request layer.
import { api } from "@/lib/api";
import type { InventoryRow, Movement, Page } from "@/types/api";

function qs(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface AdjustInput {
  warehouse_id: string;
  product_id: string;
  delta: string; // signed change to on-hand; must be non-zero
  reason: string;
}

export interface TransferInput {
  product_id: string;
  from_warehouse_id: string;
  to_warehouse_id: string;
  quantity: string;
  reason?: string | null;
}

export interface MovementListParams {
  product_id?: string;
  warehouse_id?: string;
  page?: number;
  page_size?: number;
}

export const inventoryApi = {
  adjust: (body: AdjustInput) => api.post<InventoryRow>("/inventory/adjust", body),
  transfer: (body: TransferInput) => api.post<InventoryRow[]>("/inventory/transfer", body),
  movements: (params: MovementListParams = {}) =>
    api.get<Page<Movement>>(`/inventory/movements${qs(params)}`),
  list: (params: { warehouse_id?: string; product_id?: string; page?: number; page_size?: number } = {}) =>
    api.get<Page<InventoryRow>>(`/inventory${qs(params)}`),
};
