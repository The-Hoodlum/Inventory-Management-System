// Reorder-engine API calls, built on the shared request layer.
import { api } from "@/lib/api";
import type {
  GeneratePurchaseOrdersResponse,
  Page,
  Recommendation,
  ReorderMethod,
  ReorderRunResponse,
} from "@/types/api";

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface RunReorderParams {
  window_days: number;
  safety_days: number;
  method: ReorderMethod;
  only_below_rop: boolean;
  persist: boolean;
  warehouse_id?: string;
  supplier_id?: string;
}

export interface RecommendationListParams {
  status?: string;
  warehouse_id?: string;
  supplier_id?: string;
  page?: number;
  page_size?: number;
}

export interface GeneratePurchaseOrdersBody {
  recommendation_ids: string[];
  notes?: string;
  expected_date?: string;
}

export const reorderApi = {
  // Evaluate reorder needs. With persist=true, actionable lines are saved as
  // recommendations and carry a recommendation_id used to generate POs.
  run: (params: RunReorderParams) => api.post<ReorderRunResponse>("/reorder/run", params),

  recommendations: (params: RecommendationListParams = {}) =>
    api.get<Page<Recommendation>>(
      `/reorder/recommendations${qs(params as Record<string, string | number | undefined>)}`
    ),

  // Generate draft POs from selected recommendations, grouped by (supplier, warehouse).
  generatePurchaseOrders: (body: GeneratePurchaseOrdersBody) =>
    api.post<GeneratePurchaseOrdersResponse>("/reorder/purchase-orders", body),
};
