// Panel — the token-based surface every module composes from. Theme-aware (light/dark)
// via semantic tokens; never hard-codes colors. Prefer this over a raw <div> card.
import { clsx } from "clsx";
import type { ReactNode } from "react";

export function Panel({
  className,
  children,
  padded = false,
}: {
  className?: string;
  children: ReactNode;
  padded?: boolean;
}) {
  return (
    <div
      className={clsx(
        "rounded-card border border-line bg-surface text-content shadow-card",
        padded && "p-5",
        className
      )}
    >
      {children}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="mb-1 text-content-subtle">{icon}</div>}
      <p className="text-sm font-medium text-content">{title}</p>
      {hint && <p className="max-w-sm text-sm text-muted">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-line", className)} />;
}
