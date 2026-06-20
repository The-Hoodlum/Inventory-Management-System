// Supplier scorecard API calls, built on the shared request layer.
import { api } from "@/lib/api";

export interface SupplierScore {
  id: string;
  supplier_id: string;
  supplier_name: string;
  on_time_rate: string | null;
  avg_lead_time_days: string | null;
  lead_time_stdev_days: string | null;
  lead_time_accuracy: string | null;
  fill_rate: string | null;
  delivery_performance: string | null;
  reliability: string;
  performance_risk: string;
  intelligence_risk: string;
  risk_score: string;
  grade: string;
  po_count: number;
  received_po_count: number;
  total_spend: string;
  last_order_at: string | null;
  drivers: string[] | null;
  computed_at: string;
}

export const supplierScoresApi = {
  list: () => api.get<SupplierScore[]>("/intelligence/suppliers"),
  refresh: () => api.post<{ scored: number; generated_at: string }>("/intelligence/suppliers/refresh"),
};
