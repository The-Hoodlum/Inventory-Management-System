// Motorcycle (serialized-unit) registry client. Mirrors backend app/motorcycles.
import { api } from "@/lib/api";
import type { Page } from "@/types/api";

export type UnitStatus =
  | "received"
  | "assembly_required"
  | "in_assembly"
  | "assembled"
  | "inspected"
  | "reserved"
  | "sold"
  | "delivered"
  | "registered"
  | "warranty_active"
  | "cancelled";

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

export interface MotorcycleUnit {
  id: string;
  chassis_number: string;
  engine_number: string | null;
  model: string | null;
  variant: string | null;
  colour: string | null;
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
  reserved: boolean;
  reserved_sales_order_id: string | null;
  so_number: string | null;
  sold: boolean;
  invoice_id: string | null;
  invoice_number: string | null;
  customer_id: string | null;
  customer_name: string | null;
  selling_price: number;
  price_charged: number;
  payment_status: string;
  registration_status: string;
  registration_number: string | null;
  registration_papers_received: boolean;
  warranty_start: string | null;
  warranty_end: string | null;
  notes: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  allowed_next: UnitStatus[];
  events: UnitEvent[];
}

export interface UnitListParams {
  status?: string;
  branch_id?: string;
  model?: string;
  colour?: string;
  sold?: boolean;
  search?: string;
  page?: number;
  page_size?: number;
}

export interface UnitCreate {
  chassis_number: string;
  engine_number?: string | null;
  model?: string | null;
  variant?: string | null;
  colour?: string | null;
  year?: number | null;
  supplier_id?: string | null;
  container_ref?: string | null;
  date_received?: string | null;
  branch_id?: string | null;
  warehouse_id?: string | null;
  internal_location?: string | null;
  selling_price?: number;
  assembly_required?: boolean;
  notes?: string | null;
}

export type UnitUpdate = Partial<{
  engine_number: string | null;
  model: string | null;
  variant: string | null;
  colour: string | null;
  year: number | null;
  supplier_id: string | null;
  container_ref: string | null;
  warehouse_id: string | null;
  internal_location: string | null;
  selling_price: number;
  inspection_status: string;
  assembly_status: string;
  registration_status: string;
  registration_number: string | null;
  registration_papers_received: boolean;
  warranty_start: string | null;
  warranty_end: string | null;
  notes: string | null;
  version: number;
}>;

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const motorcyclesApi = {
  list: (params: UnitListParams) =>
    api.get<Page<MotorcycleUnit>>(`/motorcycles${qs(params as Record<string, unknown>)}`),
  get: (id: string) => api.get<MotorcycleUnit>(`/motorcycles/${id}`),
  create: (body: UnitCreate) => api.post<MotorcycleUnit>("/motorcycles", body),
  update: (id: string, body: UnitUpdate) => api.patch<MotorcycleUnit>(`/motorcycles/${id}`, body),
  transition: (id: string, to_status: string, note?: string) =>
    api.post<MotorcycleUnit>(`/motorcycles/${id}/transition`, { to_status, note }),
  reserve: (id: string, body: { customer_id: string; sales_order_id?: string; note?: string }) =>
    api.post<MotorcycleUnit>(`/motorcycles/${id}/reserve`, body),
  sell: (id: string, body: { invoice_id: string; customer_id?: string; price_charged?: number; note?: string }) =>
    api.post<MotorcycleUnit>(`/motorcycles/${id}/sell`, body),
  transfer: (id: string, body: { to_branch_id: string; to_warehouse_id?: string; internal_location?: string; note?: string }) =>
    api.post<MotorcycleUnit>(`/motorcycles/${id}/transfer`, body),
};
