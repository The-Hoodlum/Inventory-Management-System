// List endpoints for catalog + stock screens, built on the shared request layer.
import { api } from "@/lib/api";
import type {
  Criticality,
  InventoryRow,
  Page,
  Product,
  ProductStatus,
  Supplier,
  SupplierStatus,
  Warehouse,
} from "@/types/api";

function qs(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || v === false) continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface ProductListParams {
  search?: string;
  status?: string;
  supplier_id?: string;
  page?: number;
  page_size?: number;
}

export interface SupplierListParams {
  search?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export interface WarehouseListParams {
  active_only?: boolean;
  page?: number;
  page_size?: number;
}

export interface InventoryListParams {
  warehouse_id?: string;
  product_id?: string;
  page?: number;
  page_size?: number;
}

export interface SupplierInput {
  name: string;
  contact_person?: string | null;
  email?: string | null;
  phone?: string | null;
  country?: string | null;
  currency: string;
  payment_terms?: string | null;
  default_lead_time_days: number;
  status: SupplierStatus;
}

export interface WarehouseInput {
  code: string;
  name: string;
  address?: string | null;
  branch_id?: string | null;
  is_active: boolean;
}

export interface ProductInput {
  sku: string;
  name: string;
  barcode?: string | null;
  description?: string | null;
  primary_supplier_id?: string | null;
  cost_price: string;
  selling_price: string;
  units_per_carton: number;
  moq: number;
  lead_time_days: number;
  reorder_point?: number | null;
  safety_stock?: number | null;
  status: ProductStatus;
  // Category/Brand by name (get-or-created server-side, matching the import flow).
  category?: string | null;
  brand?: string | null;
  // Product intelligence profile
  unit_of_measure?: string | null;
  currency?: string | null;
  commodity_tags?: string[];
  country_of_origin?: string | null;
  criticality?: Criticality;
  strategic_item?: boolean;
  alternate_supplier_available?: boolean;
}

export const catalogApi = {
  // ---- reads ----
  products: (p: ProductListParams = {}) => api.get<Page<Product>>(`/products${qs(p)}`),
  suppliers: (p: SupplierListParams = {}) => api.get<Page<Supplier>>(`/suppliers${qs(p)}`),
  warehouses: (p: WarehouseListParams = {}) => api.get<Page<Warehouse>>(`/warehouses${qs(p)}`),
  inventory: (p: InventoryListParams = {}) => api.get<Page<InventoryRow>>(`/inventory${qs(p)}`),

  // ---- suppliers ----
  createSupplier: (body: SupplierInput) => api.post<Supplier>("/suppliers", body),
  updateSupplier: (id: string, body: Partial<SupplierInput>) =>
    api.patch<Supplier>(`/suppliers/${id}`, body),
  deleteSupplier: (id: string) => api.del<void>(`/suppliers/${id}`),

  // ---- warehouses ----
  createWarehouse: (body: WarehouseInput) => api.post<Warehouse>("/warehouses", body),
  updateWarehouse: (id: string, body: Partial<WarehouseInput>) =>
    api.patch<Warehouse>(`/warehouses/${id}`, body),
  deleteWarehouse: (id: string) => api.del<void>(`/warehouses/${id}`),

  // ---- products ----
  createProduct: (body: ProductInput) => api.post<Product>("/products", body),
  updateProduct: (id: string, body: Partial<ProductInput>) =>
    api.patch<Product>(`/products/${id}`, body),
  deleteProduct: (id: string) => api.del<void>(`/products/${id}`),
};
