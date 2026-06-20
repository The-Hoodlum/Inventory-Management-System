// Reporting layer: inventory valuation, stock-status buckets, a transparent
// health score, and demand-based movers. Valuation/status are computed from the
// inventory + product endpoints; movers reuse a non-persisted reorder run.
//
// NOTE: these aggregate client-side over the full inventory list. That is fine
// for hundreds–low-thousands of stock rows; a very large catalog should move
// this to a dedicated backend report endpoint.
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { catalogApi } from "@/lib/catalog";
import { reorderApi } from "@/lib/reorder";
import { useProducts } from "@/lib/refdata";
import type { InventoryRow, Product } from "@/types/api";

const PAGE = 200;
const CAP = 20000;

async function fetchAllInventory(): Promise<InventoryRow[]> {
  const out: InventoryRow[] = [];
  let page = 1;
  for (;;) {
    const res = await catalogApi.inventory({ page, page_size: PAGE });
    out.push(...res.items);
    const total = res.total ?? out.length;
    if (res.items.length < PAGE || out.length >= total || out.length >= CAP) break;
    page += 1;
  }
  return out;
}

export type StockStatus = "out" | "low" | "ok";

export interface ReportRow {
  productId: string;
  warehouseId: string;
  sku: string;
  name: string;
  onHand: number;
  available: number;
  reserved: number;
  damaged: number;
  unitCost: number;
  unitPrice: number;
  costValue: number;
  retailValue: number;
  reorderPoint: number;
  status: StockStatus;
}

export interface WarehouseValuation {
  warehouseId: string;
  lines: number;
  onHand: number;
  costValue: number;
  retailValue: number;
}

interface Computed {
  rows: ReportRow[];
  totalCostValue: number;
  totalRetailValue: number;
  totalOnHand: number;
  byWarehouse: WarehouseValuation[];
  statusCounts: { out: number; low: number; ok: number };
  totalLines: number;
  healthScore: number;
}

export interface InventoryReport extends Computed {
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
}

function classify(available: number, reorderPoint: number): StockStatus {
  if (available <= 0) return "out";
  if (reorderPoint > 0 && available <= reorderPoint) return "low";
  return "ok";
}

function compute(inv: InventoryRow[], productMap: Map<string, Product>): Computed {
  const rows: ReportRow[] = [];
  const wh = new Map<string, WarehouseValuation>();
  const statusCounts = { out: 0, low: 0, ok: 0 };
  let totalCostValue = 0;
  let totalRetailValue = 0;
  let totalOnHand = 0;

  for (const r of inv) {
    const p = productMap.get(r.product_id);
    const onHand = Number(r.qty_on_hand);
    const available = Number(r.qty_available);
    const unitCost = p ? Number(p.cost_price) : 0;
    const unitPrice = p ? Number(p.selling_price) : 0;
    const reorderPoint = p?.reorder_point ?? 0;
    const costValue = onHand * unitCost;
    const retailValue = onHand * unitPrice;
    const status = classify(available, reorderPoint);

    statusCounts[status] += 1;
    totalCostValue += costValue;
    totalRetailValue += retailValue;
    totalOnHand += onHand;

    rows.push({
      productId: r.product_id,
      warehouseId: r.warehouse_id,
      sku: p?.sku ?? "",
      name: p?.name ?? r.product_id,
      onHand,
      available,
      reserved: Number(r.qty_reserved),
      damaged: Number(r.qty_damaged),
      unitCost,
      unitPrice,
      costValue,
      retailValue,
      reorderPoint,
      status,
    });

    const w =
      wh.get(r.warehouse_id) ??
      { warehouseId: r.warehouse_id, lines: 0, onHand: 0, costValue: 0, retailValue: 0 };
    w.lines += 1;
    w.onHand += onHand;
    w.costValue += costValue;
    w.retailValue += retailValue;
    wh.set(r.warehouse_id, w);
  }

  const totalLines = rows.length;
  const outRate = totalLines ? statusCounts.out / totalLines : 0;
  const lowRate = totalLines ? statusCounts.low / totalLines : 0;
  // Transparent score: 100 − %out − 0.4 × %low, floored at 0.
  const healthScore = totalLines
    ? Math.max(0, Math.round(100 - 100 * outRate - 40 * lowRate))
    : 100;
  const byWarehouse = [...wh.values()].sort((a, b) => b.costValue - a.costValue);

  return {
    rows,
    totalCostValue,
    totalRetailValue,
    totalOnHand,
    byWarehouse,
    statusCounts,
    totalLines,
    healthScore,
  };
}

export function useInventoryReport(): InventoryReport {
  const { map: productMap, isLoading: pLoading, isError: pError } = useProducts();
  const invQ = useQuery({
    queryKey: ["report", "inventory-all"],
    queryFn: fetchAllInventory,
    staleTime: 60_000,
  });
  const computed = useMemo(() => compute(invQ.data ?? [], productMap), [invQ.data, productMap]);
  return {
    ...computed,
    isLoading: pLoading || invQ.isLoading,
    isError: pError || invQ.isError,
    error: (invQ.error as Error | null) ?? null,
  };
}

export interface MoverRow {
  productId: string;
  sku: string;
  name: string;
  avgMonthly: number;
  avgDaily: number;
  available: number;
}

export interface MoversReport {
  rows: MoverRow[];
  generatedAt: string | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
}

export function useMovers(enabled: boolean): MoversReport {
  const q = useQuery({
    queryKey: ["report", "movers"],
    enabled,
    staleTime: 60_000,
    queryFn: () =>
      reorderApi.run({
        window_days: 90,
        safety_days: 7,
        method: "days_cover",
        only_below_rop: false,
        persist: false,
      }),
  });

  const rows = useMemo<MoverRow[]>(() => {
    const items = q.data?.items ?? [];
    const byProduct = new Map<string, MoverRow>();
    for (const it of items) {
      const cur =
        byProduct.get(it.product_id) ??
        { productId: it.product_id, sku: it.sku, name: it.name, avgMonthly: 0, avgDaily: 0, available: 0 };
      cur.avgMonthly += Number(it.avg_monthly_sales);
      cur.avgDaily += Number(it.avg_daily_demand);
      cur.available += Number(it.available);
      byProduct.set(it.product_id, cur);
    }
    return [...byProduct.values()];
  }, [q.data]);

  return {
    rows,
    generatedAt: q.data?.generated_at ?? null,
    isLoading: q.isLoading,
    isError: q.isError,
    error: (q.error as Error | null) ?? null,
  };
}
