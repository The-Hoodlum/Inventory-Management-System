// Motorcycle module API — reference catalog (models / variants / colours) and the
// per-unit serialized registry with its audited lifecycle.
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Page } from "@/types/api";

// ---- lifecycle -------------------------------------------------------------
export const UNIT_STATUSES = [
  "received", "assembly_required", "in_assembly", "assembled", "inspected",
  "reserved", "sold", "delivered", "registered", "warranty_active", "cancelled",
] as const;
export type UnitStatus = (typeof UNIT_STATUSES)[number];

export function statusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---- reference catalog -----------------------------------------------------
export interface MotoModel {
  id: string;
  tenant_id: string;
  brand_id: string;
  brand_name: string | null;
  name: string;
  category_id: string | null;
  engine_cc: number | null;
  default_selling_price: number | null;
  specs: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MotoVariant {
  id: string;
  tenant_id: string;
  model_id: string;
  model_name: string | null;
  name: string;
  specs: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MotoColour {
  id: string;
  tenant_id: string;
  name: string;
  hex_code: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ---- units -----------------------------------------------------------------
export interface UnitEvent {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  from_branch_id: string | null;
  from_branch_name: string | null;
  to_branch_id: string | null;
  to_branch_name: string | null;
  reference_type: string | null;
  reference_id: string | null;
  note: string | null;
  user_id: string | null;
  created_at: string;
}

export interface MotoUnit {
  id: string;
  chassis_number: string;
  engine_number: string | null;
  model_id: string;
  model_name: string | null;
  variant_id: string | null;
  variant_name: string | null;
  colour_id: string | null;
  colour_name: string | null;
  year: number | null;
  supplier_id: string | null;
  supplier_name: string | null;
  container_ref: string | null;
  date_received: string | null;
  branch_id: string | null;
  branch_name: string | null;
  warehouse_id: string | null;
  warehouse_name: string | null;
  internal_location: string | null;
  status: UnitStatus;
  inspection_status: string;
  assembly_status: string;
  reserved_ref: string | null;
  reserved_so_number: string | null;
  sold_ref: string | null;
  sold_invoice_number: string | null;
  customer_id: string | null;
  customer_name: string | null;
  selling_price: number | null;
  price_charged: number | null;
  payment_status: string;
  registration_status: string;
  registration_number: string | null;
  registration_papers_received: boolean;
  warranty_start: string | null;
  warranty_end: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  allowed_next: UnitStatus[];
  events: UnitEvent[];
}

export interface UnitListParams {
  search?: string;
  status?: string;
  branch_id?: string;
  model_id?: string;
  variant_id?: string;
  colour_id?: string;
  sold?: boolean;
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

export const motorcyclesApi = {
  // reference: models
  listModels: (params: { search?: string; active_only?: boolean; page?: number; page_size?: number } = {}) =>
    api.get<Page<MotoModel>>(`/motorcycles/models${qs({ page_size: 200, ...params })}`),
  createModel: (body: Record<string, unknown>) => api.post<MotoModel>("/motorcycles/models", body),
  updateModel: (id: string, body: Record<string, unknown>) => api.patch<MotoModel>(`/motorcycles/models/${id}`, body),
  // reference: variants
  listVariants: (params: { model_id?: string; active_only?: boolean; page?: number; page_size?: number } = {}) =>
    api.get<Page<MotoVariant>>(`/motorcycles/variants${qs({ page_size: 200, ...params })}`),
  createVariant: (body: Record<string, unknown>) => api.post<MotoVariant>("/motorcycles/variants", body),
  updateVariant: (id: string, body: Record<string, unknown>) => api.patch<MotoVariant>(`/motorcycles/variants/${id}`, body),
  // reference: colours
  listColours: (params: { active_only?: boolean; page?: number; page_size?: number } = {}) =>
    api.get<Page<MotoColour>>(`/motorcycles/colours${qs({ page_size: 200, ...params })}`),
  createColour: (body: Record<string, unknown>) => api.post<MotoColour>("/motorcycles/colours", body),
  updateColour: (id: string, body: Record<string, unknown>) => api.patch<MotoColour>(`/motorcycles/colours/${id}`, body),
  // units
  listUnits: (params: UnitListParams = {}) => api.get<Page<MotoUnit>>(`/motorcycles/units${qs({ ...params })}`),
  getUnit: (id: string) => api.get<MotoUnit>(`/motorcycles/units/${id}`),
  createUnit: (body: Record<string, unknown>) => api.post<MotoUnit>("/motorcycles/units", body),
  updateUnit: (id: string, body: Record<string, unknown>) => api.patch<MotoUnit>(`/motorcycles/units/${id}`, body),
  transition: (id: string, to_status: string, note?: string) =>
    api.post<MotoUnit>(`/motorcycles/units/${id}/transition`, { to_status, note }),
  reserve: (id: string, body: { customer_id: string; sales_order_id?: string; note?: string }) =>
    api.post<MotoUnit>(`/motorcycles/units/${id}/reserve`, body),
  sell: (id: string, body: { invoice_id: string; customer_id?: string; price_charged?: number; note?: string }) =>
    api.post<MotoUnit>(`/motorcycles/units/${id}/sell`, body),
  transfer: (id: string, body: { to_branch_id: string; to_warehouse_id?: string; internal_location?: string; note?: string }) =>
    api.post<MotoUnit>(`/motorcycles/units/${id}/transfer`, body),
};

export function useMotoModels() {
  return useQuery({ queryKey: ["moto", "models"], queryFn: () => motorcyclesApi.listModels(), staleTime: 60_000 });
}

export function useMotoColours() {
  return useQuery({ queryKey: ["moto", "colours"], queryFn: () => motorcyclesApi.listColours(), staleTime: 60_000 });
}
