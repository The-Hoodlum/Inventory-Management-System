// Generic data-import API calls (first target: inventory), on the shared request layer.
import { api, BASE_URL, tokenStore } from "@/lib/api";

export interface ImportField {
  name: string;
  label: string;
  required: boolean;
  kind: string;
  choices: string[];
  aliases: string[];
}

export interface ImportTarget {
  key: string;
  label: string;
  fields: ImportField[];
  template_levels: string[];
}

export type ColumnMapping = Record<string, number | null>;

export interface ValueMap {
  kind: "status" | "model" | "colour";
  value: string;                 // the sheet value being resolved
  action: "map" | "new";
  target?: string | null;        // canonical value when action === "map"
  consignment?: string | null;   // model only: batch token -> consignment field
}

export interface ImportOptions {
  warehouse_mode: "create" | "skip";
  default_warehouse: string;
  supplier_mode: "create" | "link_only";
  // Atomic targets (motorcycle units): authorize creating the new reference values
  // the preview surfaced.
  create_missing_references?: boolean;
  // Per-value map/create decisions for status / model / colour.
  value_maps?: ValueMap[];
  // Reconciliation target: authorize committing correcting adjustments when computed-vs-
  // actual deltas exist. Left false, any non-zero delta blocks the commit.
  accept_deltas?: boolean;
}

export const DEFAULT_OPTIONS: ImportOptions = {
  warehouse_mode: "create",
  default_warehouse: "MAIN",
  supplier_mode: "create",
};

export interface NewReference {
  kind: string; // model | variant | colour | supplier
  value: string;
  count: number;
}

export interface ValueResolution {
  kind: "status" | "model" | "colour";
  value: string;
  count: number;
  suggestion: string | null;
  suggested_consignment: string | null;
  can_create: boolean;
}

export interface UploadResponse {
  job_id: string;
  target_key: string;
  filename: string;
  status: string;
  total_rows: number;
  headers: string[];
  detected_mapping: ColumnMapping;
  mapping_source: "detected" | "saved";
  sample_rows: string[][];
}

export interface RowError {
  row_number: number;
  sku: string | null;
  errors: string[];
}

export interface ReconciliationLine {
  product: string;
  warehouse: string;
  computed: number;
  actual: number;
  delta: number;
}

export interface PreviewResponse {
  total_rows: number;
  valid_count: number;
  invalid_count: number;
  missing_required: string[];
  sample_errors: RowError[];
  sample_rows: string[][];
  headers: string[];
  // Atomic targets (motorcycle units):
  atomic?: boolean;
  new_references?: NewReference[];
  value_resolutions?: ValueResolution[];
  // Reconciliation target: computed-vs-actual report + whether a non-zero delta exists.
  reconciliation?: ReconciliationLine[];
  has_deltas?: boolean;
  can_commit?: boolean;
}

export interface ImportJob {
  id: string;
  target_key: string;
  filename: string;
  status: string;
  total_rows: number;
  processed_rows: number;
  imported_rows: number;
  skipped_rows: number;
  error_count: number;
  created_by: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ImportJobList {
  items: ImportJob[];
  total: number;
  page: number;
  page_size: number;
}

export const importsApi = {
  targets: () => api.get<ImportTarget[]>("/imports/targets"),
  getTarget: (key: string) => api.get<ImportTarget>(`/imports/targets/${key}`),

  upload: (key: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload<UploadResponse>(`/imports/${key}/upload`, form);
  },

  preview: (key: string, jobId: string, mapping: ColumnMapping, options: ImportOptions) =>
    api.post<PreviewResponse>(`/imports/${key}/${jobId}/preview`, { mapping, options }),

  confirm: (key: string, jobId: string, mapping: ColumnMapping, options: ImportOptions) =>
    api.post<ImportJob>(`/imports/${key}/${jobId}/confirm`, { mapping, options }),

  getJob: (jobId: string) => api.get<ImportJob>(`/imports/${jobId}`),

  list: (targetKey?: string, page = 1, pageSize = 20) =>
    api.get<ImportJobList>(
      `/imports?page=${page}&page_size=${pageSize}` +
        (targetKey ? `&target_key=${encodeURIComponent(targetKey)}` : "")
    ),

  rollback: (jobId: string) => api.post<ImportJob>(`/imports/${jobId}/rollback`),

  retry: (jobId: string) => api.post<ImportJob>(`/imports/${jobId}/retry`),

  cancel: (jobId: string) => api.post<ImportJob>(`/imports/${jobId}/cancel`),

  async downloadErrors(jobId: string): Promise<void> {
    const token = tokenStore.getAccess();
    const res = await fetch(`${BASE_URL}/imports/${jobId}/errors.csv`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Error report download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `import_${jobId.slice(0, 8)}_errors.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // Templates require auth, so fetch with the bearer token and trigger a download
  // (a plain <a download> can't send the Authorization header).
  async downloadTemplate(key: string, level: "basic" | "standard" | "advanced"): Promise<void> {
    const token = tokenStore.getAccess();
    const res = await fetch(`${BASE_URL}/imports/targets/${key}/template?level=${level}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Template download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${key}_${level}_template.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
