// Collapsible, grouped module navigation. Expands to labelled groups or collapses to an
// icon rail (desktop); on mobile it slides in as a drawer. Items are permission-filtered,
// and empty groups are hidden. Always on the deep "ink" chrome so it reads in any theme.
import { clsx } from "clsx";
import {
  ArrowLeftRight,
  Award,
  BarChart3,
  Bell,
  Bike,
  BookOpen,
  Boxes,
  Building2,
  CalendarClock,
  ChevronsLeft,
  ChevronsRight,
  ClipboardList,
  Container,
  Contact,
  CircleDollarSign,
  CreditCard,
  HandCoins,
  HandHelping,
  Hammer,
  FileText,
  History,
  Landmark,
  LayoutDashboard,
  LayoutGrid,
  LineChart,
  Package,
  PackageCheck,
  Receipt,
  RefreshCcw,
  Rewind,
  ScrollText,
  Send,
  Settings,
  ShieldAlert,
  ShoppingCart,
  Sparkles,
  Truck,
  Upload,
  Users,
  Wallet,
  Warehouse,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission: string;
}
interface NavGroup {
  label: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [
      { to: "/apps", label: "App Launcher", icon: LayoutGrid, permission: "dashboard.read" },
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, permission: "dashboard.read" },
      { to: "/notifications", label: "Notifications", icon: Bell, permission: "dashboard.read" },
      { to: "/reports", label: "Reports", icon: BarChart3, permission: "report.read" },
    ],
  },
  {
    label: "Sales",
    items: [
      { to: "/sales", label: "Sales", icon: Receipt, permission: "sales.read" },
      { to: "/sales/pending-payments", label: "Pending Payments", icon: CircleDollarSign, permission: "sales.read" },
      { to: "/parts-sales", label: "Spare Parts POS", icon: ShoppingCart, permission: "pos.use" },
      { to: "/pos", label: "Bike POS", icon: Bike, permission: "motorcycle.manage" },
      { to: "/sales-log", label: "Sales Log", icon: BarChart3, permission: "report.read" },
      { to: "/sales-report", label: "Daily / Monthly Report", icon: CalendarClock, permission: "report.read" },
      { to: "/customers", label: "Customers", icon: Contact, permission: "customer.read" },
      { to: "/motorcycles", label: "Motorcycles", icon: Bike, permission: "motorcycle.read" },
      { to: "/bike-issues", label: "Bike Issues", icon: Wrench, permission: "bike_issue.read" },
      { to: "/assembly-planner", label: "Assembly Planner", icon: Hammer, permission: "motorcycle.read" },
      { to: "/assembly-queue", label: "Assembly Queue", icon: PackageCheck, permission: "motorcycle.read" },
      { to: "/service-followup", label: "Service Follow-up", icon: CalendarClock, permission: "motorcycle.read" },
    ],
  },
  {
    label: "Finance",
    items: [
      { to: "/finance", label: "Finance Dashboard", icon: LayoutDashboard, permission: "finance.read" },
      { to: "/finance/accounts", label: "Accounts", icon: Landmark, permission: "finance.read" },
      { to: "/finance/statement", label: "Statement", icon: ScrollText, permission: "finance.read" },
      { to: "/finance/day-book", label: "Day Book", icon: BookOpen, permission: "finance.read" },
      { to: "/finance/expenses", label: "Expenses", icon: Wallet, permission: "finance.read" },
      { to: "/finance/transfers", label: "Transfers", icon: ArrowLeftRight, permission: "finance.read" },
      { to: "/finance/handovers", label: "Cash Handovers", icon: HandCoins, permission: "finance.read" },
      { to: "/finance/payment-setup", label: "Payment Setup", icon: CreditCard, permission: "finance.read" },
    ],
  },
  {
    label: "Inventory",
    items: [
      { to: "/inventory", label: "Inventory", icon: Boxes, permission: "inventory.read" },
      { to: "/movements", label: "Stock Movements", icon: History, permission: "inventory.read" },
      { to: "/products", label: "Products", icon: Package, permission: "product.read" },
      { to: "/branches", label: "Branches", icon: Building2, permission: "inventory.read" },
      { to: "/warehouses", label: "Warehouses", icon: Warehouse, permission: "inventory.read" },
    ],
  },
  {
    label: "Procurement",
    items: [
      { to: "/purchase-orders", label: "Purchase Orders", icon: FileText, permission: "po.read" },
      { to: "/reorder", label: "Reorder", icon: RefreshCcw, permission: "reorder.read" },
      { to: "/order-requests", label: "Order Requests", icon: ClipboardList, permission: "order_request.read" },
      { to: "/delivery-notes", label: "Delivery Notes", icon: Send, permission: "delivery_note.read" },
      { to: "/issuances", label: "Issuances", icon: HandHelping, permission: "delivery_note.read" },
      { to: "/customer-deliveries", label: "Customer Deliveries", icon: PackageCheck, permission: "delivery_note.read" },
      { to: "/suppliers", label: "Suppliers", icon: Truck, permission: "supplier.read" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/forecast", label: "Forecasting", icon: LineChart, permission: "reorder.read" },
      { to: "/container", label: "Containers", icon: Container, permission: "reorder.read" },
      { to: "/intelligence", label: "Intelligence", icon: ShieldAlert, permission: "reorder.read" },
      { to: "/advisor", label: "AI Analyst", icon: Sparkles, permission: "reorder.read" },
      { to: "/supplier-scores", label: "Supplier Scores", icon: Award, permission: "reorder.read" },
    ],
  },
  {
    label: "Administration",
    items: [
      { to: "/import/inventory", label: "Import Data", icon: Upload, permission: "data.import" },
      { to: "/reconstruction", label: "Reconstruct History", icon: Rewind, permission: "data.import" },
      { to: "/imports", label: "Import History", icon: History, permission: "data.import" },
      { to: "/users", label: "Users", icon: Users, permission: "user.manage" },
      { to: "/settings", label: "Settings", icon: Settings, permission: "settings.manage" },
    ],
  },
];

export function Sidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const { hasPermission } = useAuth();
  const groups = GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => hasPermission(i.permission)),
  })).filter((g) => g.items.length > 0);

  const nav = (
    <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
      {groups.map((group) => (
        <div key={group.label}>
          {!collapsed && (
            <div className="px-3 pb-1 text-2xs font-semibold uppercase tracking-wider text-slate-500">
              {group.label}
            </div>
          )}
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onCloseMobile}
                  title={collapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    clsx(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                      collapsed && "justify-center px-0",
                      isActive
                        ? "bg-brand-600 text-white"
                        : "text-slate-300 hover:bg-ink-800 hover:text-white"
                    )
                  }
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </NavLink>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

  const brand = (
    <div className={clsx("flex h-16 items-center gap-2.5 px-4 text-white", collapsed && "justify-center px-0")}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold">
        IP
      </div>
      {!collapsed && <span className="text-sm font-semibold tracking-tight">ERP Platform</span>}
    </div>
  );

  const collapseBtn = (
    <button
      onClick={onToggleCollapse}
      className="m-2 hidden items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-slate-400 hover:bg-ink-800 hover:text-white md:flex"
    >
      {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
    </button>
  );

  return (
    <>
      {/* Desktop rail */}
      <aside
        className={clsx(
          "hidden h-full shrink-0 flex-col bg-ink-900 text-slate-300 shadow-sidebar transition-[width] md:flex",
          collapsed ? "w-16" : "w-60"
        )}
      >
        {brand}
        {nav}
        {collapseBtn}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button aria-hidden className="absolute inset-0 bg-ink-950/50" onClick={onCloseMobile} />
          <aside className="absolute left-0 top-0 flex h-full w-64 flex-col bg-ink-900 text-slate-300">
            {brand}
            {nav}
          </aside>
        </div>
      )}
    </>
  );
}
