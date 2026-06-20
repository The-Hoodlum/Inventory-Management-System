import { clsx } from "clsx";
import {
  Award,
  BarChart3,
  Boxes,
  Container,
  FileText,
  History,
  LayoutDashboard,
  LineChart,
  Package,
  RefreshCcw,
  ShieldAlert,
  Sparkles,
  Truck,
  Upload,
  Users,
  Warehouse,
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

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, permission: "dashboard.read" },
  { to: "/reports", label: "Reports", icon: BarChart3, permission: "report.read" },
  { to: "/purchase-orders", label: "Purchase Orders", icon: FileText, permission: "po.read" },
  { to: "/reorder", label: "Reorder", icon: RefreshCcw, permission: "reorder.read" },
  { to: "/forecast", label: "Forecasting", icon: LineChart, permission: "reorder.read" },
  { to: "/container", label: "Containers", icon: Container, permission: "reorder.read" },
  { to: "/intelligence", label: "Intelligence", icon: ShieldAlert, permission: "reorder.read" },
  { to: "/advisor", label: "AI Analyst", icon: Sparkles, permission: "reorder.read" },
  { to: "/supplier-scores", label: "Supplier Scores", icon: Award, permission: "reorder.read" },
  { to: "/inventory", label: "Inventory", icon: Boxes, permission: "inventory.read" },
  { to: "/movements", label: "Stock Movements", icon: History, permission: "inventory.read" },
  { to: "/products", label: "Products", icon: Package, permission: "product.read" },
  { to: "/import/inventory", label: "Import Data", icon: Upload, permission: "data.import" },
  { to: "/imports", label: "Import History", icon: History, permission: "data.import" },
  { to: "/suppliers", label: "Suppliers", icon: Truck, permission: "supplier.read" },
  { to: "/warehouses", label: "Warehouses", icon: Warehouse, permission: "inventory.read" },
  { to: "/users", label: "Users", icon: Users, permission: "user.manage" },
];

export function Sidebar() {
  const { hasPermission } = useAuth();
  const items = NAV.filter((item) => hasPermission(item.permission));

  return (
    <aside className="hidden h-full w-60 shrink-0 flex-col bg-ink-900 text-slate-300 md:flex">
      <div className="flex h-16 items-center gap-2.5 px-5 text-white">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold">
          IP
        </div>
        <span className="text-sm font-semibold tracking-tight">Inventory &amp; Procurement</span>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-2">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-brand-600 text-white"
                    : "text-slate-300 hover:bg-ink-800 hover:text-white"
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
      <div className="px-5 py-4 text-2xs text-slate-500">v0.1 · {items.length} sections</div>
    </aside>
  );
}
