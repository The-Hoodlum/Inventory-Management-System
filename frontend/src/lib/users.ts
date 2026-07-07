// User-administration API client (requires the user.manage permission).
import { api } from "@/lib/api";
import type { AppUser, Page, Role } from "@/types/api";

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface UserListParams {
  search?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export interface UserCreateInput {
  email: string;
  full_name: string;
  password: string;
  role_ids: string[];
  branch_ids: string[];
  is_active: boolean;
}

export interface UserUpdateInput {
  full_name?: string;
  is_active?: boolean;
  password?: string;
  role_ids?: string[];
  branch_ids?: string[];
}

export const usersApi = {
  list: (params: UserListParams = {}) =>
    api.get<Page<AppUser>>(`/users${qs(params as Record<string, string | number | undefined>)}`),
  get: (id: string) => api.get<AppUser>(`/users/${id}`),
  roles: () => api.get<Role[]>("/users/roles"),
  create: (body: UserCreateInput) => api.post<AppUser>("/users", body),
  update: (id: string, body: UserUpdateInput) => api.patch<AppUser>(`/users/${id}`, body),
  deactivate: (id: string) => api.del<void>(`/users/${id}`),
};
