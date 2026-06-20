// Hooks for the backend's server-computed reports: inventory aging (FIFO layer
// reconstruction) and supplier performance (on-time / lead time / fill rate).
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { InventoryAgingReport, SupplierPerformanceReport } from "@/types/api";

export function useInventoryAging(warehouseId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["report", "aging", warehouseId],
    enabled,
    staleTime: 60_000,
    queryFn: () =>
      api.get<InventoryAgingReport>(
        `/reports/inventory-aging${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`
      ),
  });
}

export function useSupplierPerformance(windowDays: number, enabled: boolean) {
  return useQuery({
    queryKey: ["report", "supplier-performance", windowDays],
    enabled,
    staleTime: 60_000,
    queryFn: () =>
      api.get<SupplierPerformanceReport>(
        `/reports/supplier-performance?window_days=${windowDays}`
      ),
  });
}
