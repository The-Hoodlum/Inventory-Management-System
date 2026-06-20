import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ChevronDown, ChevronRight, Play, ShoppingCart } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard } from "@/components/ui";
import { reorderApi } from "@/lib/reorder";
import { formatDate, formatNumber, formatQty, shortId } from "@/lib/format";
import { useWarehouses } from "@/lib/refdata";
import type { ReorderLineResult, ReorderMethod } from "@/types/api";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function clampInt(value: string, min: number, max: number, fallback: number): number {
  const n = parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function clampFloat(value: string, min: number, max: number, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** A run line can be converted to a PO only if it was persisted and has a qty. */
function isSelectable(it: ReorderLineResult): boolean {
  return !!it.recommendation_id && Number(it.recommended_qty) > 0;
}

export default function ReorderPage() {
  const { hasPermission } = useAuth();
  const qc = useQueryClient();

  const { map: warehouseMap } = useWarehouses();

  const canRun = hasPermission("reorder.run");
  const canCreate = hasPermission("po.create");

  const [windowDays, setWindowDays] = useState("90");
  const [safetyDays, setSafetyDays] = useState("7");
  const [method, setMethod] = useState<ReorderMethod>("days_cover");
  const [onlyBelow, setOnlyBelow] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set<string>());
  const [expanded, setExpanded] = useState<Set<string>>(new Set<string>());
  const [err, setErr] = useState<string | null>(null);

  const toggleExpand = (k: string) =>
    setExpanded((prev) => {
      const n = new Set(prev);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  const run = useMutation({
    mutationFn: () =>
      reorderApi.run({
        window_days: clampInt(windowDays, 1, 730, 90),
        safety_days: clampFloat(safetyDays, 0, 3650, 7),
        method,
        only_below_rop: onlyBelow,
        persist: true,
      }),
    onSuccess: () => {
      setSelected(new Set<string>());
      generate.reset();
      setErr(null);
    },
    onError: (e) => setErr((e as Error).message),
  });

  const generate = useMutation({
    mutationFn: (ids: string[]) => reorderApi.generatePurchaseOrders({ recommendation_ids: ids }),
    onSuccess: () => {
      setSelected(new Set<string>());
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "metrics"] });
      setErr(null);
    },
    onError: (e) => setErr((e as Error).message),
  });

  const result = run.data;
  const items = result?.items ?? [];

  const selectableIds = useMemo(
    () => items.filter(isSelectable).map((it) => it.recommendation_id as string),
    [items]
  );
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected(() => (allSelected ? new Set<string>() : new Set<string>(selectableIds)));

  const onGenerate = () => {
    if (selected.size === 0) return;
    generate.mutate([...selected]);
  };

  return (
    <div>
      <PageHeader
        title="Reorder"
        description="Evaluate demand against stock and generate draft purchase orders for what needs replenishing."
        actions={
          <Button onClick={() => run.mutate()} disabled={!canRun || run.isPending}>
            <Play className="h-4 w-4" />
            {run.isPending ? "Analyzing…" : "Run analysis"}
          </Button>
        }
      />

      {!canRun && (
        <Card className="mb-4 p-4 text-sm text-slate-500">
          You don’t have permission to run reorder analysis.
        </Card>
      )}

      {/* Parameters */}
      <Card className="p-5">
        <h2 className="text-sm font-semibold text-slate-800">Parameters</h2>
        <div className="mt-4 flex flex-wrap items-end gap-5">
          <Field label="Demand window (days)" hint="Lookback used to estimate demand">
            <input
              type="number"
              min={1}
              max={730}
              value={windowDays}
              onChange={(e) => setWindowDays(e.target.value)}
              className={`${INPUT} w-28`}
            />
          </Field>
          <Field label="Safety days" hint="Buffer added on top of lead time">
            <input
              type="number"
              min={0}
              step="any"
              value={safetyDays}
              onChange={(e) => setSafetyDays(e.target.value)}
              className={`${INPUT} w-28`}
            />
          </Field>
          <Field label="Method" hint="Safety-stock calculation">
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value as ReorderMethod)}
              className={`${INPUT} w-44`}
            >
              <option value="days_cover">Days of cover</option>
              <option value="statistical">Statistical (service level)</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 pb-1.5 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={onlyBelow}
              onChange={(e) => setOnlyBelow(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            Only items below reorder point
          </label>
        </div>
      </Card>

      {err && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {err}
        </div>
      )}

      {generate.data && (
        <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span className="font-medium">
            Created {generate.data.created} purchase order
            {generate.data.created === 1 ? "" : "s"}.
          </span>
          {generate.data.skipped_recommendation_ids.length > 0 && (
            <span className="text-emerald-700">
              {generate.data.skipped_recommendation_ids.length} recommendation
              {generate.data.skipped_recommendation_ids.length === 1 ? "" : "s"} skipped (already
              ordered or missing a supplier).
            </span>
          )}
          <Link
            to="/purchase-orders"
            className="inline-flex items-center gap-1 font-medium text-emerald-900 underline-offset-2 hover:underline"
          >
            View purchase orders <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}

      {/* Results */}
      <div className="mt-6">
        {run.isPending ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner label="Evaluating demand and stock…" />
          </div>
        ) : !result ? (
          <Card className="p-10 text-center">
            <p className="text-sm font-medium text-slate-700">No analysis yet</p>
            <p className="mt-1 text-sm text-slate-400">
              Set your parameters and run the analysis to see what needs reordering.
            </p>
          </Card>
        ) : (
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Evaluated" value={formatNumber(result.evaluated)} hint="Product · warehouse pairs" />
              <StatCard
                label="Needs reorder"
                value={formatNumber(result.to_order)}
                tone={result.to_order > 0 ? "warning" : "positive"}
              />
              <StatCard label="Selected" value={formatNumber(selected.size)} />
              <StatCard label="As of" value={formatDate(result.generated_at)} />
            </div>

            {items.length === 0 ? (
              <Card className="p-10 text-center">
                <p className="text-sm font-medium text-slate-700">Nothing to reorder</p>
                <p className="mt-1 text-sm text-slate-400">
                  All evaluated stock is above its reorder point.
                </p>
              </Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
                  <p className="text-sm text-slate-500">
                    {selectableIds.length} of {items.length} line
                    {items.length === 1 ? "" : "s"} can be ordered
                    {selected.size > 0 ? ` · ${selected.size} selected` : ""}
                  </p>
                  <Button
                    onClick={onGenerate}
                    disabled={!canCreate || selected.size === 0 || generate.isPending}
                  >
                    <ShoppingCart className="h-4 w-4" />
                    {generate.isPending ? "Generating…" : "Generate purchase orders"}
                  </Button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th className="w-10 px-4 py-2.5">
                          <input
                            type="checkbox"
                            aria-label="Select all"
                            checked={allSelected}
                            disabled={selectableIds.length === 0}
                            onChange={toggleAll}
                            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                          />
                        </th>
                        <th className="px-4 py-2.5 font-medium">SKU</th>
                        <th className="px-4 py-2.5 font-medium">Product</th>
                        <th className="px-4 py-2.5 font-medium">Warehouse</th>
                        <th className="px-4 py-2.5 text-right font-medium">Available</th>
                        <th className="px-4 py-2.5 text-right font-medium">Reorder pt</th>
                        <th className="px-4 py-2.5 text-right font-medium">On order</th>
                        <th className="px-4 py-2.5 text-right font-medium">Recommend</th>
                        <th className="px-4 py-2.5 text-right font-medium">Cartons</th>
                        <th className="w-10 px-4 py-2.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {items.map((it) => {
                        const rowKey = `${it.product_id}:${it.warehouse_id}`;
                        const selectable = isSelectable(it);
                        const id = it.recommendation_id ?? "";
                        const checked = selectable && selected.has(id);
                        const isOpen = expanded.has(rowKey);
                        return (
                          <Fragment key={rowKey}>
                            <tr className={selectable ? "hover:bg-slate-50" : "opacity-60"}>
                              <td className="px-4 py-3">
                                <input
                                  type="checkbox"
                                  aria-label={`Select ${it.sku}`}
                                  checked={checked}
                                  disabled={!selectable}
                                  onChange={() => selectable && toggleOne(id)}
                                  className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500 disabled:opacity-40"
                                />
                              </td>
                              <td className="px-4 py-3 font-mono text-[13px] text-slate-800">{it.sku}</td>
                              <td className="px-4 py-3 text-slate-700">
                                <div className="max-w-[18rem] truncate" title={it.name}>
                                  {it.name}
                                </div>
                                {!it.supplier_id && (
                                  <span className="text-xs text-amber-600">No supplier — set one to order</span>
                                )}
                              </td>
                              <td className="px-4 py-3 text-slate-600" title={it.warehouse_id}>
                                {warehouseMap.get(it.warehouse_id)?.name ?? shortId(it.warehouse_id)}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                                {formatQty(it.available)}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                                {formatQty(it.reorder_point)}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                                {formatQty(it.on_order)}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-[13px] font-semibold text-slate-900">
                                {formatQty(it.recommended_qty)}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                                {it.recommended_cartons}
                                {it.applied_moq && (
                                  <span
                                    className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700"
                                    title="Quantity raised to the supplier minimum order quantity"
                                  >
                                    MOQ
                                  </span>
                                )}
                              </td>
                              <td className="px-4 py-3 text-right">
                                <button
                                  onClick={() => toggleExpand(rowKey)}
                                  aria-label="Explain recommendation"
                                  aria-expanded={isOpen}
                                  className="text-slate-400 hover:text-slate-700"
                                >
                                  {isOpen ? (
                                    <ChevronDown className="h-4 w-4" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4" />
                                  )}
                                </button>
                              </td>
                            </tr>
                            {isOpen && (
                              <tr className="bg-slate-50/70">
                                <td colSpan={10} className="px-4 pb-5 pt-1">
                                  <Explain it={it} />
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </label>
      <div className="mt-1.5">{children}</div>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

function ExplainRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-mono text-slate-800">{value}</span>
    </div>
  );
}

function Explain({ it }: { it: ReorderLineResult }) {
  const target = Number(it.order_up_to_level);
  const pos = Number(it.inventory_position);
  const shortfall = Math.max(0, target - pos);
  const cartonUnits = it.recommended_cartons * it.units_per_carton;
  const statistical =
    (it.safety_stock_method ?? "").toLowerCase().includes("stat") || Number(it.std_dev_daily) > 0;

  return (
    <div className="grid gap-x-8 gap-y-5 rounded-lg bg-white p-4 ring-1 ring-slate-200 lg:grid-cols-2">
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Demand inputs</h4>
        <div className="text-sm">
          <ExplainRow label="Avg daily demand" value={`${formatQty(it.avg_daily_demand)} / day`} />
          <ExplainRow label="Avg monthly sales" value={formatQty(it.avg_monthly_sales)} />
          {statistical && (
            <ExplainRow label="Demand variability (σ)" value={`${formatQty(it.std_dev_daily)} / day`} />
          )}
          <ExplainRow label="Lead time" value={`${formatQty(it.lead_time_days)} days`} />
          {Number(it.review_period_days) > 0 && (
            <ExplainRow label="Review period" value={`${formatQty(it.review_period_days)} days`} />
          )}
          <ExplainRow
            label="Safety stock"
            value={`${formatQty(it.safety_stock)} (${it.safety_stock_method})`}
          />
          <ExplainRow label="Reorder point" value={formatQty(it.reorder_point)} />
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          How the quantity was derived
        </h4>
        <div className="text-sm">
          <ExplainRow label="Order-up-to level" value={formatQty(it.order_up_to_level)} />
          <ExplainRow
            label="Inventory position"
            value={`${formatQty(it.inventory_position)}  =  ${formatQty(it.on_hand)} on hand − ${formatQty(
              it.reserved
            )} reserved + ${formatQty(it.on_order)} on order`}
          />
          <ExplainRow label="Shortfall to target" value={formatQty(shortfall)} />
          <ExplainRow
            label="Rounded up to full cartons"
            value={`${it.recommended_cartons} × ${it.units_per_carton} = ${formatNumber(cartonUnits)}`}
          />
          <ExplainRow
            label="Minimum order qty"
            value={it.applied_moq ? `${formatNumber(it.moq)} — applied` : `${formatNumber(it.moq)} — not binding`}
          />
          <div className="mt-1 flex justify-between gap-4 border-t border-slate-200 pt-2 font-semibold">
            <span className="text-slate-700">Recommended order</span>
            <span className="font-mono text-slate-900">
              {formatQty(it.recommended_qty)} ({it.recommended_cartons} cartons)
            </span>
          </div>
        </div>
      </div>

      {it.reason && (
        <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500 ring-1 ring-slate-200 lg:col-span-2">
          <span className="font-medium text-slate-600">Engine note:</span> {it.reason}
        </p>
      )}
    </div>
  );
}
