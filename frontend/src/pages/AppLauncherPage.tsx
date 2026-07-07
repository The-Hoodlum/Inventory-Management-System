// App Launcher — the ERP home. A grid of module cards (live areas link through; planned
// modules are clearly marked "Coming soon"), above a live snapshot built from the shared
// dashboard primitives (KpiCard / Grid / ChartCard) wired to the existing /dashboard data.
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Bike,
  Boxes,
  Briefcase,
  Building2,
  CircleDollarSign,
  Contact,
  Factory,
  Hammer,
  Receipt,
  Send,
  Truck,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { ChartCard, Grid, KpiCard, Panel, PageHeading, Section } from "@/components/ds";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { DashboardMetrics } from "@/types/api";

interface ModuleCard {
  title: string;
  description: string;
  icon: LucideIcon;
  to?: string;
  permission?: string;
  soon?: boolean;
}

const MODULES: ModuleCard[] = [
  { title: "Sales", description: "Quotes, orders, invoices, POS", icon: Receipt, to: "/sales", permission: "sales.read" },
  { title: "Spare Parts", description: "Sell parts & view sales log", icon: Wrench, to: "/parts-sales", permission: "pos.use" },
  { title: "Sales Log", description: "Parts + motorcycle revenue", icon: BarChart3, to: "/sales-log", permission: "report.read" },
  { title: "Inventory", description: "Stock, movements, warehouses", icon: Boxes, to: "/inventory", permission: "inventory.read" },
  { title: "Procurement", description: "Purchase orders & reorder", icon: Truck, to: "/purchase-orders", permission: "po.read" },
  { title: "Delivery Notes", description: "Transfers & dispatch notes", icon: Send, to: "/delivery-notes", permission: "delivery_note.read" },
  { title: "Customers", description: "Accounts & balances", icon: Contact, to: "/customers", permission: "customer.read" },
  { title: "Motorcycles", description: "Serialized-unit registry", icon: Bike, to: "/motorcycles", permission: "motorcycle.read" },
  { title: "Bike Issues", description: "Internal repairs & parts used", icon: AlertTriangle, to: "/bike-issues", permission: "bike_issue.read" },
  { title: "Assembly Planner", description: "What bikes to assemble next", icon: Hammer, to: "/assembly-planner", permission: "motorcycle.read" },
  { title: "Finance", description: "Ledgers, payments, tax", icon: CircleDollarSign, soon: true },
  { title: "CRM", description: "Leads & opportunities", icon: Building2, soon: true },
  { title: "Human Resources", description: "People & payroll", icon: Users, soon: true },
  { title: "Workshop", description: "Jobs & service", icon: Wrench, soon: true },
  { title: "Fleet", description: "Vehicles & logistics", icon: Briefcase, soon: true },
  { title: "Manufacturing", description: "BOM & production", icon: Factory, soon: true },
];

export default function AppLauncherPage() {
  const { hasPermission } = useAuth();
  const { data } = useQuery({
    queryKey: ["dashboard", "metrics"],
    queryFn: () => api.get<DashboardMetrics>("/dashboard/metrics"),
  });

  const poData = Object.entries(data?.purchase_orders.by_status ?? {}).map(([status, count]) => ({
    status,
    count,
  }));

  return (
    <div>
      <PageHeading
        title="App Launcher"
        description="Jump into a module, or see what’s coming next."
      />

      <Section title="Modules">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          {MODULES.map((m) => {
            const Icon = m.icon;
            const allowed = !m.permission || hasPermission(m.permission);
            const live = !m.soon && allowed && m.to;
            const card = (
              <div
                className={`group relative flex h-full flex-col gap-3 rounded-card border border-line bg-surface p-4 shadow-card transition ${
                  live ? "hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-pop" : "opacity-60"
                }`}
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-100 text-brand-700">
                  <Icon className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-content">{m.title}</span>
                    {m.soon && (
                      <span className="rounded-full bg-canvas px-2 py-0.5 text-2xs font-medium text-content-subtle">
                        Coming soon
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{m.description}</p>
                </div>
              </div>
            );
            return live ? (
              <Link key={m.title} to={m.to!}>
                {card}
              </Link>
            ) : (
              <div key={m.title} aria-disabled>
                {card}
              </div>
            );
          })}
        </div>
      </Section>

      <Section title="At a glance" description="Live snapshot from your operations data.">
        <Grid cols={4} className="mb-4">
          <KpiCard label="Products" value={formatNumber(data?.catalog.products ?? 0)} icon={<Boxes className="h-[18px] w-[18px]" />} tone="brand" />
          <KpiCard label="On hand" value={formatNumber(data?.inventory.total_on_hand ?? 0)} hint="units across locations" />
          <KpiCard
            label="Low stock"
            value={formatNumber(data?.inventory.low_stock_count ?? 0)}
            tone={(data?.inventory.low_stock_count ?? 0) > 0 ? "warning" : "positive"}
            hint="at/below reorder"
          />
          <KpiCard label="Open POs" value={formatNumber(data?.purchase_orders.open_count ?? 0)} hint="awaiting receipt" />
        </Grid>
        {poData.length > 0 ? (
          <ChartCard title="Purchase orders by status" data={poData} xKey="status" kind="bar" series={[{ key: "count", label: "POs" }]} />
        ) : (
          <Panel padded>
            <p className="text-sm text-muted">No purchase-order activity yet.</p>
          </Panel>
        )}
      </Section>
    </div>
  );
}
