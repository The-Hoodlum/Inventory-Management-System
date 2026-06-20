// Container load-planning API calls, built on the shared request layer.
import { api } from "@/lib/api";

export interface ContainerOption {
  code: string;
  label: string;
  internal_volume_m3: string;
  max_payload_kg: string;
}

export interface PlanLineOut {
  product_id: string;
  sku: string;
  cartons: number;
  volume_m3: string;
  weight_kg: string;
}

export interface TopOff {
  product_id: string;
  sku: string;
  additional_cartons: number;
  additional_units: number;
  moq_shortfall: number;
  note: string;
}

export interface ContainerPlan {
  container_code: string;
  container_label: string;
  containers_needed: number;
  total_cartons: number;
  total_volume_m3: string;
  total_weight_kg: string;
  volume_utilization: string;
  weight_utilization: string;
  binding_constraint: string;
  spare_volume_m3: string;
  spare_weight_kg: string;
  lines: PlanLineOut[];
  top_off: TopOff | null;
  drivers: string[];
  skipped_product_ids: string[];
}

export interface PlanLineInput {
  product_id: string;
  cartons?: number;
  units?: number;
}

export const containerApi = {
  containers: () => api.get<ContainerOption[]>("/container/containers"),
  plan: (body: { lines: PlanLineInput[]; container_code?: string | null }) =>
    api.post<ContainerPlan>("/container/plan", body),
  planFromRecs: (body: { recommendation_ids: string[]; container_code?: string | null }) =>
    api.post<ContainerPlan>("/container/plan/from-recommendations", body),
};
