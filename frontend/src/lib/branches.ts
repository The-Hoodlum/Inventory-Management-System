// Branch admin API. A branch is a tenant-scoped site that owns warehouses; the
// motorcycle import (and stock transfers) match branches BY NAME, so this screen is
// how you create/rename them. Reads need inventory.read; mutations need warehouse.manage.
import { api } from "@/lib/api";
import type { Branch, Page } from "@/types/api";

export interface BranchInput {
  name: string;
  code: string;
  is_active?: boolean;
}

export const branchesApi = {
  list: (params: { active_only?: boolean; page?: number; page_size?: number } = {}) => {
    const p = new URLSearchParams();
    p.set("page", String(params.page ?? 1));
    p.set("page_size", String(params.page_size ?? 100));
    if (params.active_only) p.set("active_only", "true");
    return api.get<Page<Branch>>(`/branches?${p.toString()}`);
  },
  create: (body: BranchInput) => api.post<Branch>("/branches", body),
  update: (id: string, body: Partial<BranchInput>) => api.patch<Branch>(`/branches/${id}`, body),
};

export type { Branch };
