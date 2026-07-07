// Bike Issues API — record an INTERNAL repair on a bike we own and consume the spare
// part(s) used to fix it. Not a customer sale: the part is an internal cost. Consumption
// runs through the single inventory write path (server-side); resolving commits it and
// returns the bike to its prior sellable status.
import { api } from "@/lib/api";
import type { Page } from "@/types/api";

export type BikeIssueStatus = "open" | "in_repair" | "resolved";

export function issueStatusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface RepairLine {
  id: string;
  product_id: string;
  sku: string | null;
  name: string | null;
  warehouse_id: string;
  warehouse_name: string | null;
  quantity: number;
  consumed: boolean;
  consumed_at: string | null;
  remarks: string | null;
}

export interface BikeIssue {
  id: string;
  issue_number: string;
  status: BikeIssueStatus;
  unit_id: string;
  chassis_number: string;
  engine_number: string | null;
  model_name: string | null;
  branch_id: string | null;
  branch_name: string | null;
  prior_status: string;
  problem_description: string;
  reported_at: string;
  reported_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  notes: string | null;
  created_at: string;
  lines: RepairLine[];
}

export interface RepairLineInput {
  product_id: string;
  warehouse_id: string;
  quantity: number;
  remarks?: string;
}

export interface CreateBikeIssueBody {
  unit_id: string;
  problem_description: string;
  notes?: string;
  lines?: RepairLineInput[];
}

export interface ResolveBikeIssueBody {
  resolution_note?: string;
  lines?: RepairLineInput[];
}

export interface ListBikeIssuesParams {
  status?: string;
  branch_id?: string;
  unit_id?: string;
  model_id?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const bikeIssuesApi = {
  list: (params: ListBikeIssuesParams = {}) => api.get<Page<BikeIssue>>(`/bike-issues${qs({ ...params })}`),
  get: (id: string) => api.get<BikeIssue>(`/bike-issues/${id}`),
  create: (body: CreateBikeIssueBody) => api.post<BikeIssue>("/bike-issues", body),
  addLine: (id: string, body: RepairLineInput) => api.post<BikeIssue>(`/bike-issues/${id}/lines`, body),
  removeLine: (id: string, lineId: string) => api.del<BikeIssue>(`/bike-issues/${id}/lines/${lineId}`),
  setStatus: (id: string, status: "open" | "in_repair") => api.post<BikeIssue>(`/bike-issues/${id}/status`, { status }),
  resolve: (id: string, body: ResolveBikeIssueBody = {}) => api.post<BikeIssue>(`/bike-issues/${id}/resolve`, body),
};
