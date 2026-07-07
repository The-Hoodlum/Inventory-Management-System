// Assembly Planner API — deterministic recommendation of which bikes to assemble, from
// CURRENT stock (assembled vs unassembled counts). No demand prediction. Recommends only;
// assembling is the existing unassembled->assembled transition in the Motorcycle module.
import { api } from "@/lib/api";

export interface AssemblyLine {
  model_id: string;
  model_name: string | null;
  variant_id: string | null;
  variant_name: string | null;
  colour_id: string | null;
  colour_name: string | null;
  current_assembled: number;
  unassembled_available: number;
  target_assembled: number;
  threshold: number;
  recommended_qty: number;
  reason: string;
}

export interface AssemblyPlan {
  generated_at: string;
  default_target_assembled: number;
  default_threshold: number;
  recommendations: AssemblyLine[];
  gaps: AssemblyLine[];
}

export interface AssemblyTarget {
  id: string;
  model_id: string;
  model_name: string | null;
  colour_id: string | null;
  colour_name: string | null;
  target_assembled: number;
  threshold: number;
}

export interface AssemblyTargetInput {
  model_id: string;
  colour_id?: string | null;
  target_assembled: number;
  threshold: number;
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const assemblyApi = {
  plan: (params: { branch_id?: string; model_id?: string } = {}) =>
    api.get<AssemblyPlan>(`/assembly/plan${qs({ ...params })}`),
  listTargets: () => api.get<AssemblyTarget[]>("/assembly/targets"),
  upsertTarget: (body: AssemblyTargetInput) => api.put<AssemblyTarget>("/assembly/targets", body),
  deleteTarget: (id: string) => api.del<void>(`/assembly/targets/${id}`),
};
