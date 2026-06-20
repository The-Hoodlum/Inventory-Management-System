// Supply-chain intelligence API calls, built on the shared request layer.
import { api } from "@/lib/api";
import type {
  IngestResponse,
  IntelligenceDashboard,
  IntelligenceSignal,
  ManualSignalBody,
  Page,
} from "@/types/api";

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface SignalListParams {
  category?: string;
  scope_type?: string;
  page?: number;
  page_size?: number;
}

export const intelligenceApi = {
  dashboard: () => api.get<IntelligenceDashboard>("/intelligence/dashboard"),

  signals: (params: SignalListParams = {}) =>
    api.get<Page<IntelligenceSignal>>(
      `/intelligence/signals${qs(params as Record<string, string | number | undefined>)}`
    ),

  // Recompute the computed providers (supplier risk) and any wired external feeds.
  ingest: () => api.post<IngestResponse>("/intelligence/ingest", { categories: [] }),

  // Analyst-entered observation (freight/port/commodity/trade/geopolitical/supplier).
  recordSignal: (body: ManualSignalBody) =>
    api.post<IntelligenceSignal>("/intelligence/signals", body),
};
