// Page scaffolds — assemble a module screen from shared parts instead of hand-rolling.
// PageHeading: token-based title bar.  ListPage: heading + DataTable.  DetailScaffold:
// loading/error/empty handling around a detail view (usually a FormLayout).
import type { ReactNode } from "react";

import { Spinner } from "@/components/ui";
import { DataTable, type DataTableProps } from "./DataTable";
import { EmptyState, Panel } from "./Panel";

export function PageHeading({
  title,
  description,
  actions,
  icon,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {icon && (
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-100 text-brand-700">
            {icon}
          </div>
        )}
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-content">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ListPage<Row>({
  title,
  description,
  actions,
  icon,
  table,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  icon?: ReactNode;
  table: DataTableProps<Row>;
}) {
  return (
    <div>
      <PageHeading title={title} description={description} actions={actions} icon={icon} />
      <DataTable<Row> {...table} />
    </div>
  );
}

export function DetailScaffold({
  loading,
  error,
  notFound,
  children,
}: {
  loading?: boolean;
  error?: unknown;
  notFound?: boolean;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Spinner label="Loading…" />
      </div>
    );
  }
  if (error) {
    return (
      <Panel className="p-6 text-sm text-red-600">
        Couldn’t load this record. {(error as Error | null)?.message ?? ""}
      </Panel>
    );
  }
  if (notFound) {
    return (
      <Panel>
        <EmptyState title="Not found" hint="This record may have been removed." />
      </Panel>
    );
  }
  return <>{children}</>;
}
