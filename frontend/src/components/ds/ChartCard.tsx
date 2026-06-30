// Chart wrappers around the repo's existing chart lib (recharts — no new dependency).
// A thin, consistent surface so modules drop in a line/bar/area chart without wiring
// recharts each time. Colors come from the shared CHART_PALETTE (brand-led).
import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Panel } from "./Panel";

export const CHART_PALETTE = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

const GRID = "rgba(148,163,184,0.25)";
const AXIS = "rgba(148,163,184,0.9)";

export interface Series {
  key: string;
  label?: string;
  color?: string;
}

interface BaseProps {
  title?: string;
  actions?: ReactNode;
  data: Record<string, unknown>[];
  xKey: string;
  series: Series[];
  height?: number;
  kind?: "line" | "bar" | "area";
}

function ChartFrame({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <Panel className="p-4">
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h3 className="text-sm font-semibold text-content">{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </Panel>
  );
}

const axisProps = {
  stroke: AXIS,
  tick: { fill: AXIS, fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

const tooltipStyle = {
  contentStyle: {
    borderRadius: 10,
    border: "1px solid rgba(148,163,184,0.3)",
    fontSize: 12,
  },
} as const;

export function ChartCard({ title, actions, data, xKey, series, height = 240, kind = "line" }: BaseProps) {
  return (
    <ChartFrame title={title} actions={actions}>
      <ResponsiveContainer width="100%" height={height}>
        {kind === "bar" ? (
          <BarChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
            <XAxis dataKey={xKey} {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip {...tooltipStyle} />
            {series.map((s, i) => (
              <Bar key={s.key} dataKey={s.key} name={s.label ?? s.key}
                   fill={s.color ?? CHART_PALETTE[i % CHART_PALETTE.length]} radius={[4, 4, 0, 0]} />
            ))}
          </BarChart>
        ) : kind === "area" ? (
          <AreaChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
            <XAxis dataKey={xKey} {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip {...tooltipStyle} />
            {series.map((s, i) => {
              const color = s.color ?? CHART_PALETTE[i % CHART_PALETTE.length];
              return (
                <Area key={s.key} dataKey={s.key} name={s.label ?? s.key} stroke={color}
                      fill={color} fillOpacity={0.12} strokeWidth={2} />
              );
            })}
          </AreaChart>
        ) : (
          <LineChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
            <XAxis dataKey={xKey} {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip {...tooltipStyle} />
            {series.map((s, i) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label ?? s.key}
                    stroke={s.color ?? CHART_PALETTE[i % CHART_PALETTE.length]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </ChartFrame>
  );
}
