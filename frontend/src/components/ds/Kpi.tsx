// KpiCard — a dashboard metric tile. Tone drives the accent; an optional delta shows
// trend. Theme-aware via tokens. Use inside a <Grid> for executive/ops dashboards.
import { clsx } from "clsx";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";

import { Panel } from "./Panel";

type Tone = "default" | "brand" | "positive" | "warning" | "danger";

const TONE: Record<Tone, string> = {
  default: "text-content",
  brand: "text-brand-600",
  positive: "text-emerald-600",
  warning: "text-amber-600",
  danger: "text-red-600",
};

const ICON_BG: Record<Tone, string> = {
  default: "bg-line text-content-muted",
  brand: "bg-brand-100 text-brand-700",
  positive: "bg-emerald-100 text-emerald-700",
  warning: "bg-amber-100 text-amber-700",
  danger: "bg-red-100 text-red-700",
};

export function KpiCard({
  label,
  value,
  hint,
  icon,
  tone = "default",
  delta,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  tone?: Tone;
  delta?: { value: string; direction: "up" | "down"; good?: boolean };
}) {
  const deltaGood = delta?.good ?? delta?.direction === "up";
  return (
    <Panel className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
          <div className={clsx("mt-2 text-2xl font-semibold tabular", TONE[tone])}>{value}</div>
          {hint && <div className="mt-1 text-xs text-subtle">{hint}</div>}
        </div>
        {icon && (
          <div className={clsx("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", ICON_BG[tone])}>
            {icon}
          </div>
        )}
      </div>
      {delta && (
        <div
          className={clsx(
            "mt-3 inline-flex items-center gap-1 text-xs font-medium",
            deltaGood ? "text-emerald-600" : "text-red-600"
          )}
        >
          {delta.direction === "up" ? (
            <ArrowUpRight className="h-3.5 w-3.5" />
          ) : (
            <ArrowDownRight className="h-3.5 w-3.5" />
          )}
          {delta.value}
        </div>
      )}
    </Panel>
  );
}
