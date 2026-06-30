// AI assistant client. Wraps the existing /assistant/ask endpoint (the model never
// touches the DB — it runs through permission-gated, RLS-scoped tools server-side).
import { api } from "@/lib/api";

export interface AskResponse {
  answer: string;
  // The backend may include richer fields (used tools, data) — kept open here.
  [k: string]: unknown;
}

export const assistantApi = {
  ask: (question: string) => api.post<AskResponse>("/assistant/ask", { question }),
};
