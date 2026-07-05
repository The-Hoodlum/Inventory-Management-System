// Internal issuance / handover (out-and-back loan) API. Issuing makes stock temporarily
// not-sellable without a permanent deduction (bikes out-on-loan, items held); returning
// releases it. Never touches stock directly.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export type IssuanceStatus = "draft" | "out_on_loan" | "partially_returned" | "returned" | "cancelled";
export type Condition = "good" | "fair" | "needs_attention";

export function issuanceStatusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface IssuanceLine {
  id: string;
  line_kind: "motorcycle" | "part";
  product_id: string | null;
  sku: string | null;
  name: string | null;
  unit_id: string | null;
  chassis_number: string | null;
  engine_number: string | null;
  model_name: string | null;
  qty: number;
  returnable: boolean;
  consumable: boolean;
  odometer_out: number | null;
  fuel_out: string | null;
  accessories: string | null;
  returned_qty: number;
  missing_qty: number;
  condition: string | null;
  odometer_in: number | null;
  return_note: string | null;
  returned_at: string | null;
  remarks: string | null;
}

export interface Issuance {
  id: string;
  issuance_number: string;
  status: IssuanceStatus;
  branch_id: string | null;
  branch_name: string | null;
  warehouse_id: string;
  warehouse_name: string | null;
  requestor: string | null;
  department: string | null;
  purpose: string | null;
  expected_return_date: string | null;
  overdue: boolean;
  remarks: string | null;
  issued_at: string | null;
  closed_at: string | null;
  created_at: string;
  lines: IssuanceLine[];
}

export interface CreateIssuanceBody {
  warehouse_id: string;
  requestor?: string;
  department?: string;
  purpose?: string;
  expected_return_date?: string | null;
  remarks?: string;
  part_lines?: { product_id: string; qty: number; returnable?: boolean; consumable?: boolean }[];
  bike_lines?: { unit_id: string; odometer_out?: number; fuel_out?: string; accessories?: string }[];
}

export interface ReturnIssuanceBody {
  remarks?: string;
  part_lines?: { line_id: string; returned_qty: number }[];
  bike_lines?: { line_id: string; condition: Condition; odometer_in?: number; return_note?: string }[];
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const issuanceApi = {
  list: (params: { branch_id?: string; status?: string; open?: boolean } = {}) =>
    api.get<Issuance[]>(`/issuances${qs(params)}`),
  get: (id: string) => api.get<Issuance>(`/issuances/${id}`),
  create: (body: CreateIssuanceBody) => api.post<Issuance>("/issuances", body),
  issue: (id: string) => api.post<Issuance>(`/issuances/${id}/issue`),
  return: (id: string, body: ReturnIssuanceBody) => api.post<Issuance>(`/issuances/${id}/return`, body),
  cancel: (id: string, reason?: string) => api.post<Issuance>(`/issuances/${id}/cancel`, { reason: reason ?? null }),

  async downloadPdf(id: string, issuanceNumber: string): Promise<void> {
    const token = tokenStore.getAccess();
    const res = await fetch(`${BASE_URL}/issuances/${id}/pdf`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new Error(`PDF download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${issuanceNumber}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
