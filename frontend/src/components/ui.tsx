import { clsx } from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("rounded-xl border border-slate-200 bg-white shadow-card", className)}>
      {children}
    </div>
  );
}

type StatTone = "default" | "positive" | "warning" | "danger";

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: StatTone;
}) {
  const toneClass: Record<StatTone, string> = {
    default: "text-slate-900",
    positive: "text-emerald-600",
    warning: "text-amber-600",
    danger: "text-red-600",
  };
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={clsx("mt-2 text-2xl font-semibold tabular", toneClass[tone])}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </Card>
  );
}

const STATUS_TONES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  pending_approval: "bg-amber-100 text-amber-800",
  approved: "bg-brand-100 text-brand-800",
  rejected: "bg-red-100 text-red-700",
  sent: "bg-indigo-100 text-indigo-700",
  partially_received: "bg-cyan-100 text-cyan-800",
  received: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-200 text-slate-600",
  // order-request statuses
  pending: "bg-amber-100 text-amber-800",
  partially_approved: "bg-cyan-100 text-cyan-800",
  issued: "bg-emerald-100 text-emerald-700",
  completed: "bg-teal-100 text-teal-800",
  // catalog / reference statuses
  active: "bg-emerald-100 text-emerald-700",
  inactive: "bg-slate-200 text-slate-600",
  discontinued: "bg-red-100 text-red-700",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_TONES[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        cls
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost";
}

export function Button({ variant = "primary", className, ...props }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";
  const variants: Record<NonNullable<ButtonProps["variant"]>, string> = {
    primary: "bg-brand-600 text-white hover:bg-brand-700",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
  };
  return <button className={clsx(base, variants[variant], className)} {...props} />;
}
