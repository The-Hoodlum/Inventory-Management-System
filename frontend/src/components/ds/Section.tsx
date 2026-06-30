// Section + Grid — page layout primitives. A Section is a titled block with optional
// actions; Grid lays KPI cards / panels out responsively. Compose these instead of
// hand-rolling fl/grid wrappers per page.
import { clsx } from "clsx";
import type { ReactNode } from "react";

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("mb-6", className)}>
      {(title || actions) && (
        <div className="mb-3 flex items-end justify-between gap-4">
          <div>
            {title && <h2 className="text-sm font-semibold text-content">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

const COLS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
  4: "grid-cols-2 lg:grid-cols-4",
};

export function Grid({
  cols = 3,
  children,
  className,
}: {
  cols?: 1 | 2 | 3 | 4;
  children: ReactNode;
  className?: string;
}) {
  return <div className={clsx("grid gap-4", COLS[cols], className)}>{children}</div>;
}
