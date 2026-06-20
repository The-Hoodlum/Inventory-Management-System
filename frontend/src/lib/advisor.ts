// AI Supply Chain Analyst API calls, built on the shared request layer.
import { api } from "@/lib/api";

export interface Finding {
  category: string;
  severity: string; // Decimal serialised as string
  title: string;
  detail: string;
  refs: Record<string, unknown>;
  recommended_action: string | null;
}

export interface AdvisoryBriefing {
  generated_at: string;
  summary: string;
  llm_enabled: boolean;
  narrative: string | null;
  metrics: Record<string, number>;
  findings: Finding[];
}

export interface AdvisoryAnswer {
  question: string;
  generated_at: string;
  llm_enabled: boolean;
  answer: string | null;
  relevant_findings: Finding[];
  metrics: Record<string, number>;
}

export const advisorApi = {
  // Deterministic, explainable briefing (LLM narrative added when configured).
  briefing: () => api.get<AdvisoryBriefing>("/advisor/briefing"),

  // Free-text question -> relevant findings now, LLM answer when a key is set.
  ask: (question: string) => api.post<AdvisoryAnswer>("/advisor/ask", { question }),
};
