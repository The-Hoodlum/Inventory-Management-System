import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatCard } from "@/components/ui";
import {
  DEFAULT_OPTIONS,
  importsApi,
  type ColumnMapping,
  type ImportJob,
  type ImportOptions,
  type PreviewResponse,
  type UploadResponse,
} from "@/lib/imports";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

type Step = "upload" | "map" | "done";

// Where "view imported records" should land, per target.
const VIEW: Record<string, { path: string; label: string }> = {
  inventory: { path: "/products", label: "View products" },
  suppliers: { path: "/suppliers", label: "View suppliers" },
  warehouses: { path: "/warehouses", label: "View warehouses" },
};

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

export default function ImportInventoryPage() {
  const navigate = useNavigate();
  const [targetKey, setTargetKey] = useState("inventory");
  const [step, setStep] = useState<Step>("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>({});
  const [options, setOptions] = useState<ImportOptions>(DEFAULT_OPTIONS);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [result, setResult] = useState<ImportJob | null>(null);

  const { data: targets } = useQuery({ queryKey: ["import-targets"], queryFn: importsApi.targets });
  const { data: target } = useQuery({
    queryKey: ["import-target", targetKey],
    queryFn: () => importsApi.getTarget(targetKey),
  });

  function reset() {
    setStep("upload");
    setUpload(null);
    setMapping({});
    setPreview(null);
    setResult(null);
    setError(null);
  }

  function onTargetChange(key: string) {
    setTargetKey(key);
    reset();
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await importsApi.upload(targetKey, file);
      setUpload(res);
      setMapping(res.detected_mapping);
      setStep("map");
      const pv = await importsApi.preview(targetKey, res.job_id, res.detected_mapping, options);
      setPreview(pv);
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function revalidate(nextMapping = mapping, nextOptions = options) {
    if (!upload) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await importsApi.preview(targetKey, upload.job_id, nextMapping, nextOptions));
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function runImport() {
    if (!upload) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await importsApi.confirm(targetKey, upload.job_id, mapping, options));
      setStep("done");
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const view = VIEW[targetKey] ?? { path: "/products", label: "Done" };

  return (
    <div>
      <PageHeader
        title="Import Data"
        description="Upload an Excel or CSV file to load records into the system. Pick what you're importing, then map columns and confirm."
        actions={
          <label className="flex items-center gap-2 text-sm">
            <span className="text-slate-500">Import:</span>
            <select
              className={`${INPUT} w-44`}
              value={targetKey}
              onChange={(e) => onTargetChange(e.target.value)}
              disabled={step !== "upload"}
            >
              {(targets ?? []).map((t) => (
                <option key={t.key} value={t.key}>{t.label}</option>
              ))}
            </select>
          </label>
        }
      />

      <Stepper step={step} />

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {step === "upload" && (
        <UploadStep targetKey={targetKey} busy={busy} onFile={onFile} />
      )}

      {step === "map" && upload && target && (
        <MapStep
          upload={upload}
          fields={target.fields}
          mapping={mapping}
          options={options}
          preview={preview}
          busy={busy}
          showInventoryOptions={targetKey === "inventory"}
          onMappingChange={(name, idx) => {
            const next = { ...mapping, [name]: idx };
            setMapping(next);
            void revalidate(next, options);
          }}
          onOptionsChange={(next) => {
            setOptions(next);
            void revalidate(mapping, next);
          }}
          onImport={runImport}
        />
      )}

      {step === "done" && result && (
        <DoneStep
          result={result}
          viewLabel={view.label}
          onReset={reset}
          onView={() => navigate(view.path)}
        />
      )}
    </div>
  );
}

function Stepper({ step }: { step: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "upload", label: "1 · Upload" },
    { key: "map", label: "2 · Map & preview" },
    { key: "done", label: "3 · Result" },
  ];
  const order: Step[] = ["upload", "map", "done"];
  return (
    <div className="mb-5 flex items-center gap-2 text-sm">
      {steps.map((s) => {
        const active = s.key === step;
        const done = order.indexOf(s.key) < order.indexOf(step);
        return (
          <span
            key={s.key}
            className={
              "rounded-full px-3 py-1 font-medium " +
              (active
                ? "bg-brand-600 text-white"
                : done
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-slate-100 text-slate-500")
            }
          >
            {s.label}
          </span>
        );
      })}
    </div>
  );
}

function UploadStep({
  targetKey,
  busy,
  onFile,
}: {
  targetKey: string;
  busy: boolean;
  onFile: (f: File | undefined) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card className="p-6 md:col-span-2">
        <label className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-slate-300 px-6 py-12 text-center hover:border-brand-400">
          <Upload className="h-8 w-8 text-brand-600" />
          <span className="text-sm font-medium text-slate-700">
            Click to choose a .xlsx, .xls or .csv file
          </span>
          <span className="text-xs text-slate-400">
            The first row must be column headers; download a template below for the exact columns.
          </span>
          <input
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            disabled={busy}
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </label>
        {busy && (
          <div className="mt-4">
            <Spinner label="Reading file…" />
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
          <FileSpreadsheet className="h-4 w-4" /> Starter templates
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Download a ready-made header row and fill in your data.
        </p>
        <div className="space-y-2">
          {(["basic", "standard", "advanced"] as const).map((lvl) => (
            <Button
              key={lvl}
              variant="secondary"
              className="w-full justify-start capitalize"
              onClick={() => void importsApi.downloadTemplate(targetKey, lvl)}
            >
              <Download className="h-4 w-4" /> {lvl} template
            </Button>
          ))}
        </div>
      </Card>
    </div>
  );
}

function MapStep({
  upload,
  fields,
  mapping,
  options,
  preview,
  busy,
  showInventoryOptions,
  onMappingChange,
  onOptionsChange,
  onImport,
}: {
  upload: UploadResponse;
  fields: { name: string; label: string; required: boolean }[];
  mapping: ColumnMapping;
  options: ImportOptions;
  preview: PreviewResponse | null;
  busy: boolean;
  showInventoryOptions: boolean;
  onMappingChange: (name: string, idx: number | null) => void;
  onOptionsChange: (o: ImportOptions) => void;
  onImport: () => void;
}) {
  const missing = preview?.missing_required ?? [];
  const canImport = !busy && missing.length === 0 && (preview?.valid_count ?? 0) > 0;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* Mapping */}
      <Card className="p-5 lg:col-span-2">
        <div className="mb-3 text-sm font-semibold text-slate-700">
          Column mapping · {upload.filename} ({upload.total_rows} rows)
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {fields.map((f) => (
            <label key={f.name} className="flex items-center justify-between gap-2 text-sm">
              <span className="text-slate-600">
                {f.label}
                {f.required && <span className="text-red-500"> *</span>}
              </span>
              <select
                className={`${INPUT} w-40`}
                value={mapping[f.name] ?? ""}
                onChange={(e) =>
                  onMappingChange(f.name, e.target.value === "" ? null : Number(e.target.value))
                }
              >
                <option value="">— skip —</option>
                {upload.headers.map((h, i) => (
                  <option key={i} value={i}>
                    {h}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>

        {showInventoryOptions && (
          <>
            <div className="mt-5 mb-2 text-sm font-semibold text-slate-700">Options</div>
            <div className="grid gap-3 sm:grid-cols-3 text-sm">
              <label className="flex flex-col gap-1">
                <span className="text-slate-500">Unknown warehouse</span>
                <select
                  className={INPUT}
                  value={options.warehouse_mode}
                  onChange={(e) =>
                    onOptionsChange({ ...options, warehouse_mode: e.target.value as ImportOptions["warehouse_mode"] })
                  }
                >
                  <option value="create">Create it</option>
                  <option value="skip">Skip the row</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-slate-500">Default warehouse</span>
                <input
                  className={INPUT}
                  value={options.default_warehouse}
                  onChange={(e) => onOptionsChange({ ...options, default_warehouse: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-slate-500">Unknown supplier</span>
                <select
                  className={INPUT}
                  value={options.supplier_mode}
                  onChange={(e) =>
                    onOptionsChange({ ...options, supplier_mode: e.target.value as ImportOptions["supplier_mode"] })
                  }
                >
                  <option value="create">Create it</option>
                  <option value="link_only">Leave blank</option>
                </select>
              </label>
            </div>
          </>
        )}

        {/* Sample data */}
        <div className="mt-5 mb-2 text-sm font-semibold text-slate-700">Preview (first rows)</div>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                {upload.headers.map((h, i) => (
                  <th key={i} className="px-2 py-1 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {upload.sample_rows.map((row, ri) => (
                <tr key={ri} className="border-t border-slate-100">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-1 text-slate-700">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Validation + import */}
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
          Validation {busy && <Spinner />}
        </div>
        {missing.length > 0 && (
          <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Map these required fields: {missing.join(", ")}
          </div>
        )}
        {preview && (
          <div className="grid grid-cols-2 gap-2">
            <StatCard label="Valid rows" value={preview.valid_count} tone="positive" />
            <StatCard label="Invalid rows" value={preview.invalid_count} tone={preview.invalid_count ? "danger" : "default"} />
          </div>
        )}
        {preview && preview.sample_errors.length > 0 && (
          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold text-slate-600">Sample errors</div>
            <ul className="max-h-48 space-y-1 overflow-y-auto text-xs text-red-700">
              {preview.sample_errors.map((e) => (
                <li key={e.row_number}>
                  Row {e.row_number}: {e.errors.join("; ")}
                </li>
              ))}
            </ul>
          </div>
        )}
        <Button className="mt-4 w-full" disabled={!canImport} onClick={onImport}>
          Import {preview ? `${preview.valid_count} rows` : ""}
        </Button>
      </Card>
    </div>
  );
}

const TERMINAL = ["completed", "cancelled", "failed"];

function etaText(job: ImportJob): string {
  if (!job.started_at || job.processed_rows <= 0 || job.processed_rows >= job.total_rows) return "";
  const elapsedSec = (Date.now() - new Date(job.started_at).getTime()) / 1000;
  const rate = job.processed_rows / elapsedSec; // rows/sec
  if (rate <= 0) return "";
  const remaining = (job.total_rows - job.processed_rows) / rate;
  return remaining > 90 ? `~${Math.ceil(remaining / 60)} min left` : `~${Math.ceil(remaining)} s left`;
}

function DoneStep({
  result,
  viewLabel,
  onReset,
  onView,
}: {
  result: ImportJob;
  viewLabel: string;
  onReset: () => void;
  onView: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const { data } = useQuery({
    queryKey: ["import-job", result.id],
    queryFn: () => importsApi.getJob(result.id),
    initialData: result,
    refetchInterval: (q) =>
      q.state.data && TERMINAL.includes(q.state.data.status) ? false : 1000,
  });
  const job = data ?? result;
  const terminal = TERMINAL.includes(job.status);
  const pct =
    job.total_rows > 0
      ? Math.min(100, Math.round((job.processed_rows / job.total_rows) * 100))
      : terminal
        ? 100
        : 0;

  async function cancel() {
    setCancelling(true);
    try {
      await importsApi.cancel(result.id);
    } finally {
      setCancelling(false);
    }
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center gap-2 text-lg font-semibold capitalize text-slate-800">
        {terminal ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-600" />
        ) : (
          <Spinner />
        )}
        Import {job.status.replace(/_/g, " ")}
      </div>

      {/* Progress bar */}
      <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
        <span>
          {job.processed_rows} / {job.total_rows} rows ({pct}%)
        </span>
        {!terminal && <span>{etaText(job)}</span>}
      </div>
      <div className="mb-5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={"h-full transition-all " + (terminal ? "bg-emerald-500" : "bg-brand-600")}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard label="Total rows" value={job.total_rows} />
        <StatCard label="Imported" value={job.imported_rows} tone="positive" />
        <StatCard label="Skipped" value={job.skipped_rows} tone={job.skipped_rows ? "warning" : "default"} />
        <StatCard label="Errors" value={job.error_count} tone={job.error_count ? "danger" : "default"} />
      </div>

      <div className="mt-5 flex gap-3">
        {terminal ? (
          <>
            <Button onClick={onView}>{viewLabel}</Button>
            <Button variant="secondary" onClick={onReset}>
              Import another file
            </Button>
          </>
        ) : (
          <Button variant="secondary" disabled={cancelling} onClick={cancel}>
            {cancelling ? "Cancelling…" : "Cancel import"}
          </Button>
        )}
      </div>
    </Card>
  );
}
