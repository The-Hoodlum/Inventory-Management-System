// Tenant business-identity settings (industry-agnostic) API.
import { api } from "@/lib/api";

export interface TenantSettings {
  company_name: string;
  brand_name: string | null;
  industry: string | null;
  default_currency: string;
  // Current USD -> billing-currency rate (numeric serialized as a string), e.g. "20.000000".
  fx_rate: string;
  // Current VAT rate as a fraction (string), e.g. "0.160000" == 16%.
  vat_rate: string;
  country: string | null;
  timezone: string;
  logo_url: string | null;
  branding_colors: Record<string, string>;
  assistant_name: string | null;
  assistant_prompt: string | null;
  feature_flags: Record<string, boolean>;
}

export type TenantSettingsUpdate = Partial<
  Omit<TenantSettings, "feature_flags" | "branding_colors">
> & {
  feature_flags?: Record<string, boolean>;
  branding_colors?: Record<string, string>;
};

// Mirror of the backend's canonical flags (app/core/feature_flags.py) for labels/order.
export const FEATURE_LABELS: { key: string; label: string }[] = [
  { key: "inventory", label: "Inventory" },
  { key: "purchase_orders", label: "Purchase Orders" },
  { key: "order_requests", label: "Order Requests" },
  { key: "reorder_engine", label: "Reorder Engine" },
  { key: "forecasting", label: "Forecasting" },
  { key: "supply_chain_intelligence", label: "Supply Chain Intelligence" },
  { key: "whatsapp_assistant", label: "WhatsApp Assistant" },
  { key: "multi_warehouse", label: "Multi-Warehouse" },
  { key: "barcode_scanning", label: "Barcode Scanning" },
  { key: "sales_orders", label: "Sales Orders" },
  { key: "manufacturing", label: "Manufacturing" },
  { key: "expiry_tracking", label: "Expiry Tracking" },
];

export const tenantApi = {
  get: () => api.get<TenantSettings>("/tenant/settings"),
  update: (body: TenantSettingsUpdate) => api.put<TenantSettings>("/tenant/settings", body),
};
