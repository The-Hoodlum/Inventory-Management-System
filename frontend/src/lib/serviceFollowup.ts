// Motorcycle service follow-up API — the call-back list for sold bikes (next service due,
// computed time-only and scaled by how hard the bike is ridden), logging a service,
// setting a bike's usage profile, and editing the per-model service schedule.
import { api } from "@/lib/api";

export type ServiceUsage = "light" | "medium" | "heavy";
export type DueStatus = "overdue" | "due_soon" | "upcoming";

export const USAGE_LABELS: Record<ServiceUsage, string> = {
  light: "Light — commuting",
  medium: "Medium — delivery",
  heavy: "Heavy — rural / farm",
};

export interface FollowUpRow {
  unit_id: string;
  chassis_number: string;
  model_id: string;
  model_name: string | null;
  colour_name: string | null;
  branch_id: string | null;
  branch_name: string | null;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  date_sold: string | null;
  service_usage: ServiceUsage;
  services_done: number;
  last_service_date: string | null;
  next_sequence: number | null;
  next_label: string | null;
  next_due_date: string | null;
  days_until_due: number | null;
  status: DueStatus | null;
}

export interface FollowUpKpis {
  overdue: number;
  due_soon: number;
  upcoming: number;
  total: number;
}

export interface FollowUpPage {
  items: FollowUpRow[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  kpis: FollowUpKpis;
}

export interface ServiceRecord {
  id: string;
  unit_id: string;
  sequence: number;
  label: string | null;
  service_date: string;
  note: string | null;
  performed_by: string | null;
  created_at: string;
}

export interface Stage {
  sequence: number;
  label: string;
  interval_days: number;
}

export interface ServicePlan {
  id: string | null;
  model_id: string | null;
  model_name: string | null;
  is_default: boolean;
  is_module_default: boolean;
  stages: Stage[];
}

export interface ServicePlans {
  plans: ServicePlan[];
  module_default: ServicePlan;
  usage_multipliers: Record<string, number>;
}

export interface StageInput {
  label?: string | null;
  interval_days: number;
}

export interface ServicePlanInput {
  model_id?: string | null;
  stages: StageInput[];
}

export interface FollowUpParams {
  status?: DueStatus | "";
  branch_id?: string;
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

export const serviceFollowupApi = {
  list: (params: FollowUpParams = {}) =>
    api.get<FollowUpPage>(`/service-followup${qs({ ...params })}`),
  listRecords: (unitId: string) =>
    api.get<ServiceRecord[]>(`/service-followup/units/${unitId}/records`),
  logService: (unitId: string, body: { service_date: string; note?: string | null; sequence?: number | null }) =>
    api.post<ServiceRecord>(`/service-followup/units/${unitId}/records`, body),
  setUsage: (unitId: string, service_usage: ServiceUsage) =>
    api.patch<FollowUpRow>(`/service-followup/units/${unitId}/usage`, { service_usage }),
  listPlans: () => api.get<ServicePlans>("/service-followup/plans"),
  upsertPlan: (body: ServicePlanInput) => api.put<ServicePlan>("/service-followup/plans", body),
  deletePlan: (id: string) => api.del<void>(`/service-followup/plans/${id}`),
};
