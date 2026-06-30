// Design-system barrel. Import shared building blocks from one place:
//   import { DataTable, FormLayout, KpiCard, ChartCard, ListPage } from "@/components/ds";
export { Panel, EmptyState, Skeleton } from "./Panel";
export { Section, Grid } from "./Section";
export { KpiCard } from "./Kpi";
export { ChartCard, CHART_PALETTE, type Series } from "./ChartCard";
export {
  DataTable,
  initialTableState,
  type Column,
  type DataTableState,
  type DataTableProps,
  type SortDir,
} from "./DataTable";
export {
  FormLayout,
  SidePanel,
  Timeline,
  type FormTab,
  type FormLayoutProps,
  type TimelineItem,
} from "./FormLayout";
export { PageHeading, ListPage, DetailScaffold } from "./PageScaffold";
