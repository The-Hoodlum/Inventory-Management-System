// Global-search client. One endpoint backs the shell's command palette; the backend
// fans across every entity the user may see (see app/search). Results are grouped.
import { api } from "@/lib/api";

export interface SearchHit {
  entity: string;
  id: string;
  title: string;
  subtitle: string | null;
  badge: string | null;
  href: string;
}

export interface SearchGroup {
  entity: string;
  label: string;
  hits: SearchHit[];
}

export interface SearchResponse {
  query: string;
  groups: SearchGroup[];
}

export const searchApi = {
  query: (q: string, signal?: AbortSignal) =>
    api.get<SearchResponse>(`/search?q=${encodeURIComponent(q)}`, signal),
};
