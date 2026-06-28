// Reference data shared across screens. Suppliers, warehouses and products are
// small, slow-changing reference sets; we load them once (paging through) and
// cache them so other screens can resolve IDs to human-readable names.
//
// For very large catalogs a future optimization is to have the backend embed
// product/supplier/warehouse names directly in PO and inventory payloads; this
// client-side cache keeps the UI readable without that change.
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { api } from "@/lib/api";
import type { Branch, Page, Product, Supplier, Warehouse } from "@/types/api";

async function fetchAll<T>(path: string, pageSize = 200, cap = 5000): Promise<T[]> {
  const out: T[] = [];
  let page = 1;
  for (;;) {
    const res = await api.get<Page<T>>(`${path}?page=${page}&page_size=${pageSize}`);
    out.push(...res.items);
    if (res.items.length === 0 || out.length >= res.total || out.length >= cap) break;
    page += 1;
  }
  return out;
}

const STALE = 5 * 60 * 1000;

export interface RefData<T> {
  list: T[];
  map: Map<string, T>;
  isLoading: boolean;
  isError: boolean;
}

function toMap<T extends { id: string }>(items: T[] | undefined): Map<string, T> {
  return new Map((items ?? []).map((it) => [it.id, it] as const));
}

export function useSuppliers(): RefData<Supplier> {
  const q = useQuery({
    queryKey: ["ref", "suppliers"],
    queryFn: () => fetchAll<Supplier>("/suppliers"),
    staleTime: STALE,
  });
  const map = useMemo(() => toMap(q.data), [q.data]);
  return { list: q.data ?? [], map, isLoading: q.isLoading, isError: q.isError };
}

export function useBranches(): RefData<Branch> {
  const q = useQuery({
    queryKey: ["ref", "branches"],
    queryFn: () => fetchAll<Branch>("/branches"),
    staleTime: STALE,
  });
  const map = useMemo(() => toMap(q.data), [q.data]);
  return { list: q.data ?? [], map, isLoading: q.isLoading, isError: q.isError };
}

export function useWarehouses(): RefData<Warehouse> {
  const q = useQuery({
    queryKey: ["ref", "warehouses"],
    queryFn: () => fetchAll<Warehouse>("/warehouses"),
    staleTime: STALE,
  });
  const map = useMemo(() => toMap(q.data), [q.data]);
  return { list: q.data ?? [], map, isLoading: q.isLoading, isError: q.isError };
}

export function useProducts(): RefData<Product> {
  const q = useQuery({
    queryKey: ["ref", "products"],
    queryFn: () => fetchAll<Product>("/products"),
    staleTime: STALE,
  });
  const map = useMemo(() => toMap(q.data), [q.data]);
  return { list: q.data ?? [], map, isLoading: q.isLoading, isError: q.isError };
}
