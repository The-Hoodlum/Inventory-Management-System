// Customer Handover API. A handover is the signed record that a customer physically
// received their motorcycle (paper form: Customer Copy + Internal Copy). It is created
// against an existing invoice + serialized unit; the motorcycle / customer / invoice data
// is pulled from those records. Completing it marks the unit delivered (an independent
// lifecycle fact) and stamps the warranty — it never touches stock.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export type HandoverStatus = "DRAFT" | "COMPLETED";
export type FuelLevel = "E" | "1" | "2" | "3" | "4" | "F";
export type PaymentMethod = "Cash" | "Bank Transfer" | "Airtel Money" | "Other";

export const APPROVAL_ROLES = [
  "mechanic_inspector",
  "assembly_technician",
  "quality_control_officer",
  "salesperson",
  "branch_manager",
] as const;
export type ApprovalRole = (typeof APPROVAL_ROLES)[number];

export const ROLE_LABELS: Record<ApprovalRole, string> = {
  mechanic_inspector: "Mechanic / Inspector",
  assembly_technician: "Assembly Technician",
  quality_control_officer: "Quality Control Officer",
  salesperson: "Salesperson",
  branch_manager: "Branch Manager",
};

// Checklist / training / accessory boolean fields, in paper-form order (field, label).
export const CHECKLIST_FIELDS: [string, string][] = [
  ["motorcycle_washed", "Motorcycle washed"],
  ["battery_connected", "Battery connected"],
  ["engine_tested", "Engine tested"],
  ["brakes_tested", "Brakes tested"],
  ["lights_working", "Lights working"],
  ["indicators_working", "Indicators working"],
  ["horn_working", "Horn working"],
  ["mirrors_fitted", "Mirrors fitted"],
  ["tyre_pressure_checked", "Tyre pressure checked"],
  ["chain_adjusted", "Chain adjusted"],
  ["oil_level_checked", "Oil level checked"],
  ["throttle_operation_checked", "Throttle operation checked"],
  ["toolkit_supplied", "Toolkit supplied"],
  ["owners_manual_supplied", "Owner's manual supplied"],
  ["warranty_book_supplied", "Warranty book supplied"],
  ["spare_key_supplied", "Spare key supplied"],
];
export const TRAINING_FIELDS: [string, string][] = [
  ["controls_explained", "Controls explained"],
  ["break_in_period_explained", "Break-in period explained"],
  ["service_schedule_explained", "Service schedule explained"],
  ["warranty_terms_explained", "Warranty terms explained"],
  ["safe_riding_explained", "Safe riding explained"],
  ["maintenance_tips_explained", "Maintenance tips explained"],
];
export const ACCESSORY_FIELDS: [string, string][] = [
  ["helmet", "Helmet"],
  ["reflector_jacket", "Reflector jacket"],
  ["spare_key", "Spare key"],
];

export const FUEL_LABELS: Record<FuelLevel, string> = {
  E: "Empty",
  "1": "1/4",
  "2": "1/2",
  "3": "3/4",
  "4": "3/4",
  F: "Full",
};

export interface Approval {
  role: ApprovalRole;
  name: string | null;
  signed: boolean;
  signed_at: string | null;
}

export interface Handover {
  id: string;
  handover_no: string;
  status: HandoverStatus;
  invoice_id: string | null;
  invoice_number: string | null;
  sales_order_id: string | null;
  unit_id: string;
  branch_id: string | null;
  branch_name: string | null;
  salesperson_id: string | null;
  salesperson_display: string | null;
  chassis_number: string | null;
  engine_number: string | null;
  model_name: string | null;
  colour_name: string | null;
  delivery_date: string | null;
  warranty_start_date: string | null;
  odometer_reading_km: number | null;
  fuel_level_at_delivery: FuelLevel | null;
  full_name: string | null;
  nrc_passport_no: string | null;
  phone: string | null;
  whatsapp: string | null;
  email: string | null;
  physical_address: string | null;
  // checklist / training / accessory booleans are accessed dynamically
  [key: string]: unknown;
  checklist_remarks: string | null;
  training_remarks: string | null;
  other_items: string | null;
  payment_method: PaymentMethod | null;
  amount_paid_zmw: number;
  balance_zmw: number;
  invoice_amount_zmw: number;
  internal_remarks: string | null;
  approvals: Approval[];
  customer_signature_name: string | null;
  customer_signed_at: string | null;
  salesperson_signature_name: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface HandoverLookup {
  unit_id: string;
  invoice_id: string | null;
  invoice_number: string | null;
  chassis_number: string | null;
  engine_number: string | null;
  model_name: string | null;
  colour_name: string | null;
  customer_id: string | null;
  customer_name: string | null;
  phone: string | null;
  email: string | null;
  branch_id: string | null;
  branch_name: string | null;
  salesperson_display: string | null;
  invoice_amount_zmw: number;
  amount_paid_zmw: number;
  balance_zmw: number;
  existing_handover_id: string | null;
}

// A patch payload is any subset of the editable fields.
export type HandoverPatch = Record<string, unknown>;

export interface CreateHandoverBody extends HandoverPatch {
  unit_id: string;
  invoice_id?: string | null; // absent for bulk-imported historical sales
}

export function handoverStatusLabel(s: string): string {
  return s === "COMPLETED" ? "Completed" : "Draft";
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const handoversApi = {
  list: (params: { branch_id?: string; status?: string; search?: string; date_from?: string; date_to?: string } = {}) =>
    api.get<Handover[]>(`/handovers${qs(params)}`),
  get: (id: string) => api.get<Handover>(`/handovers/${id}`),
  lookup: (chassis: string) => api.get<HandoverLookup>(`/handovers/lookup${qs({ chassis })}`),
  create: (body: CreateHandoverBody) => api.post<Handover>("/handovers", body),
  update: (id: string, body: HandoverPatch) => api.patch<Handover>(`/handovers/${id}`, body),
  complete: (id: string, fields?: HandoverPatch) =>
    api.post<Handover>(`/handovers/${id}/complete`, fields ? { fields } : {}),

  async downloadPdf(id: string, handoverNo: string, copy: "customer" | "internal" | "both" = "both"): Promise<void> {
    const token = tokenStore.getAccess();
    const res = await fetch(`${BASE_URL}/handovers/${id}/pdf?copy=${copy}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`PDF download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${handoverNo}${copy === "both" ? "" : `-${copy}`}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
