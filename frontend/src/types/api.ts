// Types mirroring the backend API schemas.

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUser {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  roles: string[];
  permissions: string[];
  accessible_warehouse_ids: string[]; // explicit branch grants; empty = all branches
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

// ---- Dashboard ----
export interface CatalogMetrics {
  products: number;
  suppliers: number;
  warehouses: number;
}

export interface InventoryMetrics {
  total_on_hand: string;
  total_available: string;
  total_reserved: string;
  low_stock_count: number;
}

export interface PurchaseOrderMetrics {
  by_status: Record<string, number>;
  open_count: number;
  open_value: string;
}

export interface ActivityMetrics {
  receipts_last_30d: number;
}

export interface DashboardMetrics {
  catalog: CatalogMetrics;
  inventory: InventoryMetrics;
  purchase_orders: PurchaseOrderMetrics;
  activity: ActivityMetrics;
  generated_at: string;
}

// ---- Purchase orders (used by later screens) ----
export type POStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "sent"
  | "partially_received"
  | "received"
  | "cancelled";

export interface POLine {
  id: string;
  product_id: string;
  ordered_qty: string;
  ordered_cartons: number | null;
  unit_cost: string;
  line_total: string;
  received_qty: string;
  remaining_qty: string;
}

export interface PurchaseOrder {
  id: string;
  po_number: string;
  supplier_id: string;
  warehouse_id: string;
  status: POStatus;
  currency: string;
  fx_rate: string;
  subtotal: string;
  tax: string;
  total: string;
  notes: string | null;
  order_date: string;
  expected_date: string | null;
  created_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  lines: POLine[];
}

export interface POEvent {
  id: string;
  po_id: string;
  action: string;
  from_status: string | null;
  to_status: string | null;
  comment: string | null;
  detail: Record<string, unknown> | null;
  actor_id: string | null;
  created_at: string;
}

export interface ReceiptResult {
  purchase_order: PurchaseOrder;
  received_now: string;
  fully_received: boolean;
  movements_created: number;
}

// ---- Reorder ----
export type ReorderMethod = "days_cover" | "statistical";

// One evaluated (product, warehouse) line returned by a reorder run.
// Decimal values arrive as strings; counts as numbers.
export interface ReorderLineResult {
  product_id: string;
  sku: string;
  name: string;
  warehouse_id: string;
  supplier_id: string | null;
  avg_daily_demand: string;
  avg_monthly_sales: string;
  std_dev_daily: string;
  lead_time_days: string;
  review_period_days: string;
  units_per_carton: number;
  moq: number;
  safety_stock: string;
  safety_stock_method: string;
  reorder_point: string;
  order_up_to_level: string;
  on_hand: string;
  reserved: string;
  available: string;
  on_order: string;
  inventory_position: string;
  should_reorder: boolean;
  recommended_qty: string;
  recommended_cartons: number;
  applied_moq: boolean;
  reason: string;
  // Present only when the run persisted this line (required to convert to a PO).
  recommendation_id: string | null;
}

export interface ReorderRunResponse {
  generated_at: string;
  window_days: number;
  evaluated: number;
  to_order: number;
  items: ReorderLineResult[];
}

export interface Recommendation {
  id: string;
  product_id: string;
  warehouse_id: string;
  supplier_id: string | null;
  available_qty: string;
  on_order_qty: string;
  avg_daily_demand: string;
  reorder_point: string;
  safety_stock: string;
  recommended_qty: string;
  recommended_cartons: number;
  status: string;
  generated_at: string;
}

// Subset of the backend PurchaseOrderOut we actually display after generation.
export interface GeneratedPOSummary {
  id: string;
  po_number: string;
  status: POStatus;
  currency: string;
  total: string;
}

export interface GeneratePurchaseOrdersResponse {
  created: number;
  purchase_orders: GeneratedPOSummary[];
  skipped_recommendation_ids: string[];
}

// ---- Catalog & stock ----
export type ProductStatus = "active" | "inactive" | "discontinued";
export type Criticality = "low" | "medium" | "high" | "critical";

export interface Product {
  id: string;
  tenant_id: string;
  sku: string;
  barcode: string | null;
  name: string;
  description: string | null;
  category_id: string | null;
  brand_id: string | null;
  category_name: string | null;
  brand_name: string | null;
  primary_supplier_id: string | null;
  cost_price: string;
  selling_price: string;
  wholesale_price: string;
  units_per_carton: number;
  moq: number;
  lead_time_days: number;
  weight_per_unit: string | null;
  volume_per_unit: string | null;
  weight_per_carton: string | null;
  volume_per_carton: string | null;
  cartons_per_pallet: number | null;
  reorder_point: number | null;
  safety_stock: number | null;
  // Product intelligence profile
  commodity_tags: string[];
  country_of_origin: string | null;
  criticality: Criticality;
  strategic_item: boolean;
  alternate_supplier_available: boolean;
  unit_of_measure: string | null;
  currency: string | null;
  status: ProductStatus;
  created_at: string;
  updated_at: string;
}

export type SupplierStatus = "active" | "inactive";

export interface Supplier {
  id: string;
  tenant_id: string;
  name: string;
  contact_person: string | null;
  email: string | null;
  phone: string | null;
  country: string | null;
  currency: string;
  payment_terms: string | null;
  default_lead_time_days: number;
  status: SupplierStatus;
  created_at: string;
  updated_at: string;
}

export interface Branch {
  id: string;
  tenant_id: string;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Warehouse {
  id: string;
  tenant_id: string;
  code: string;
  name: string;
  address: string | null;
  branch_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface InventoryRow {
  id: string | null;
  product_id: string;
  warehouse_id: string;
  qty_on_hand: string;
  qty_reserved: string;
  qty_damaged: string;
  qty_available: string;
  version: number;
}

export interface Movement {
  id: string;
  product_id: string;
  warehouse_id: string;
  movement_type: string;
  quantity: string;
  reference_type: string | null;
  reference_id: string | null;
  from_warehouse_id: string | null;
  to_warehouse_id: string | null;
  unit_cost: string | null;
  reason: string | null;
  user_id: string | null;
  created_at: string;
}

// ---- Server-computed reports (backend /reports/*) ----
export interface AgingBucket {
  label: string;
  min_days: number;
  max_days: number | null;
  qty: string;
  cost_value: string;
}

export interface AgingItem {
  product_id: string;
  sku: string;
  name: string;
  warehouse_id: string;
  on_hand: string;
  cost_value: string;
  oldest_received_at: string | null;
  bucket_qty: Record<string, string>;
}

export interface InventoryAgingReport {
  as_of: string;
  buckets: AgingBucket[];
  items: AgingItem[];
}

export interface SupplierPerformanceRow {
  supplier_id: string;
  supplier_name: string;
  default_lead_time_days: number;
  po_count: number;
  received_po_count: number;
  on_time_po_count: number;
  on_time_rate: number | null;
  avg_lead_time_days: number | null;
  fill_rate: number | null;
  last_order_at: string | null;
}

export interface SupplierPerformanceReport {
  as_of: string;
  window_days: number | null;
  suppliers: SupplierPerformanceRow[];
}

export interface StockPositionRow {
  branch_id: string | null;
  branch_name: string | null;
  location_id: string;
  location_name: string | null;
  product_id: string;
  sku: string | null;
  name: string | null;
  on_hand: string;
  reserved: string;
  available: string;
  in_transit: string;
}

export interface StockPositionReport {
  as_of: string;
  rows: StockPositionRow[];
}

// ---- Unified sales log (backend /reports/sales-log) ----
export type SalesLogGranularity = "daily" | "weekly" | "monthly";
export type SalesLogType = "all" | "parts" | "motorcycles";

export interface SalesLogComponent {
  type: "parts" | "motorcycle_new" | "motorcycle_historical";
  label: string;
  units: number;
  revenue: number;
}

export interface SalesLogRow {
  period_start: string;
  period_end: string;
  label: string;
  units: number;
  revenue: number;
  components: SalesLogComponent[];
}

export interface SalesLogTotals {
  units: number;
  revenue: number;
  parts_units: number;
  parts_revenue: number;
  motorcycle_units: number;
  motorcycle_revenue: number;
  historical_units: number;
  historical_revenue: number;
}

export interface SalesLogReport {
  granularity: SalesLogGranularity;
  type: SalesLogType;
  branch_id: string | null;
  date_from: string;
  date_to: string;
  rows: SalesLogRow[];
  totals: SalesLogTotals;
}

// ---- User administration (backend /users) ----
export interface AppUser {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  roles: string[];      // role names, for display
  role_ids: string[];   // for editing
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
}

// ---- Supply-chain intelligence (backend /intelligence) ----
export type IntelligenceCategory =
  | "freight"
  | "port"
  | "commodity"
  | "trade"
  | "supplier"
  | "geopolitical";

export type IntelligenceScopeType =
  | "global"
  | "country"
  | "supplier"
  | "commodity"
  | "route"
  | "port";

export interface IntelligenceSignal {
  id: string;
  category: string;
  scope_type: string;
  scope_key: string | null;
  severity: string;
  demand_factor: string;
  confidence: string;
  headline: string;
  value: string | null;
  unit: string | null;
  trend: string | null;
  source: string;
  observed_at: string;
  expires_at: string | null;
}

export interface IntelligenceDashboard {
  risk_score: string;
  forecast_impact: string; // composite demand factor (1.0 = no change)
  confidence: string;
  active_signals: number;
  by_category: Record<string, string>;
  recommended_actions: string[];
  drivers: string[];
  generated_at: string;
}

export interface IngestResponse {
  ingested: number;
  by_category: Record<string, number>;
  by_source: Record<string, number>;
}

export interface ManualSignalBody {
  category: IntelligenceCategory;
  scope_type: IntelligenceScopeType;
  scope_key?: string | null;
  severity: number;
  demand_factor?: number;
  confidence?: number;
  headline: string;
  trend?: "up" | "down" | "flat" | null;
}
