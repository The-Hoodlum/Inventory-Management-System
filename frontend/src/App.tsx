import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { AppShell } from "@/components/AppShell";
import AdvisorPage from "@/pages/AdvisorPage";
import AppLauncherPage from "@/pages/AppLauncherPage";
import ContainerPage from "@/pages/ContainerPage";
import CustomersPage from "@/pages/CustomersPage";
import DashboardPage from "@/pages/DashboardPage";
import ForecastPage from "@/pages/ForecastPage";
import ImportHistoryPage from "@/pages/ImportHistoryPage";
import ImportInventoryPage from "@/pages/ImportInventoryPage";
import IntelligencePage from "@/pages/IntelligencePage";
import InventoryPage from "@/pages/InventoryPage";
import LoginPage from "@/pages/LoginPage";
import MotorcycleDetailPage from "@/pages/MotorcycleDetailPage";
import MotorcyclesPage from "@/pages/MotorcyclesPage";
import MotorcycleSetupPage from "@/pages/MotorcycleSetupPage";
import MovementsPage from "@/pages/MovementsPage";
import NewPurchaseOrderPage from "@/pages/NewPurchaseOrderPage";
import NotFoundPage from "@/pages/NotFoundPage";
import OrderRequestsPage from "@/pages/OrderRequestsPage";
import PosPage from "@/pages/PosPage";
import ProductsPage from "@/pages/ProductsPage";
import PurchaseOrderDetailPage from "@/pages/PurchaseOrderDetailPage";
import PurchaseOrdersPage from "@/pages/PurchaseOrdersPage";
import ReorderPage from "@/pages/ReorderPage";
import ReportsPage from "@/pages/ReportsPage";
import SalesPage from "@/pages/SalesPage";
import SettingsPage from "@/pages/SettingsPage";
import SupplierScoresPage from "@/pages/SupplierScoresPage";
import SuppliersPage from "@/pages/SuppliersPage";
import UsersPage from "@/pages/UsersPage";
import WarehousesPage from "@/pages/WarehousesPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Navigate to="/apps" replace />} />
        <Route path="/apps" element={<AppLauncherPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
        <Route path="/purchase-orders/new" element={<NewPurchaseOrderPage />} />
        <Route path="/purchase-orders/:id" element={<PurchaseOrderDetailPage />} />
        <Route path="/reorder" element={<ReorderPage />} />
        <Route path="/forecast" element={<ForecastPage />} />
        <Route path="/container" element={<ContainerPage />} />
        <Route path="/intelligence" element={<IntelligencePage />} />
        <Route path="/advisor" element={<AdvisorPage />} />
        <Route path="/supplier-scores" element={<SupplierScoresPage />} />
        <Route path="/order-requests" element={<OrderRequestsPage />} />
        <Route path="/sales" element={<SalesPage />} />
        <Route path="/customers" element={<CustomersPage />} />
        <Route path="/motorcycles" element={<MotorcyclesPage />} />
        <Route path="/motorcycles/setup" element={<MotorcycleSetupPage />} />
        <Route path="/motorcycles/:id" element={<MotorcycleDetailPage />} />
        <Route path="/pos" element={<PosPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/import/inventory" element={<ImportInventoryPage />} />
        <Route path="/imports" element={<ImportHistoryPage />} />
        <Route path="/movements" element={<MovementsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/products" element={<ProductsPage />} />
        <Route path="/suppliers" element={<SuppliersPage />} />
        <Route path="/warehouses" element={<WarehousesPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
