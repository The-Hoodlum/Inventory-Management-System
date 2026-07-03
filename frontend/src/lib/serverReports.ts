// Hooks for the backend's server-computed reports: inventory aging (FIFO layer
// reconstruction) and supplier performance (on-time / lead time / fill rate).
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  InventoryAgingReport,
  SalesLogGranularity,
  SalesLogReport,
  SalesLogType,
  StockPositionReport,
  SupplierPerformanceReport,
} from "@/types/api";

export interface SalesLogParams {
  granularity: SalesLogGranularity;
  type: SalesLogType;
  branchId?: string;
  dateFrom?: string;
  dateTo?: string;
}

export function useSalesLog(params: SalesLogParams, enabled = true) {
  const { granularity, type, branchId, dateFrom, dateTo } = params;
  const sp = new URLSearchParams({ granularity, type });
  if (branchId) sp.set("branch_id", branchId);
  if (dateFrom) sp.set("date_from", dateFrom);
  if (dateTo) sp.set("date_to", dateTo);
  return useQuery({
    queryKey: ["report", "sales-log", granularity, type, branchId ?? "", dateFrom ?? "", dateTo ?? ""],
    enabled,
    staleTime: 30_000,
    queryFn: () => api.get<SalesLogReport>(`/reports/sales-log?${sp.toString()}`),
  });
}

export function useStockPosition(branchId: string, warehouseId: string, enabled: boolean) {
  const params = new URLSearchParams();
  if (branchId) params.set("branch_id", branchId);
  if (warehouseId) params.set("warehouse_id", warehouseId);
  const qs = params.toString();
  return useQuery({
    queryKey: ["report", "stock-position", branchId, warehouseId],
    enabled,
    staleTime: 30_000,
    queryFn: () => api.get<StockPositionReport>(`/reports/stock-position${qs ? `?${qs}` : ""}`),
  });
}

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
