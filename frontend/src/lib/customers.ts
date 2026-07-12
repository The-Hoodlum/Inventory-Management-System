// Customer master API.
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Page } from "@/types/api";

export interface CustomerAddress {
  id: string;
  customer_id: string;
  address_type: "billing" | "shipping" | "other";
  line1: string | null;
  line2: string | null;
  city: string | null;
  region: string | null;
  country: string | null;
  is_default: boolean;
  created_at: string;
}

export interface Customer {
  id: string;
  tenant_id: string;
  code: string;
  name: string;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  tax_number: string | null;
  currency: string | null;
  payment_terms: string | null;
  credit_limit: number;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  addresses: CustomerAddress[];
}

export interface CustomerSummary extends Customer {
  outstanding_balance: number;
  available_credit: number | null;
}

export interface CustomerAddressInput {
  address_type?: string;
  line1?: string | null;
  line2?: string | null;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  is_default?: boolean;
}

export interface CustomerInput {
  name: string;
  contact_name?: string | null;
  phone?: string | null;
  email?: string | null;
  tax_number?: string | null;
  currency?: string | null;
  payment_terms?: string | null;
  credit_limit?: number;
  notes?: string | null;
  addresses?: CustomerAddressInput[];
}

export const customersApi = {
  list: (search = "") =>
    api.get<Page<Customer>>(`/customers?page_size=200${search ? `&search=${encodeURIComponent(search)}` : ""}`),
  get: (id: string) => api.get<CustomerSummary>(`/customers/${id}`),
  create: (body: CustomerInput) => api.post<Customer>("/customers", body),
  update: (id: string, body: Partial<CustomerInput>) => api.patch<Customer>(`/customers/${id}`, body),
};

export function useCustomers(search = "") {
  return useQuery({
    queryKey: ["customers", search],
    queryFn: () => customersApi.list(search),
    staleTime: 30_000,
  });
}
