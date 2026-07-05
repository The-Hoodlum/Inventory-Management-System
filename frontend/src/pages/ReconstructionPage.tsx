// Inventory-history Reconstruction wizard: three guided steps on the shared imports
// framework — (1) opening balances as of a period start, (2) a chronological transaction
// replay through the real inventory engine, (3) the reconciliation gate that proves the
// computed stock matches the counted reality before it is trusted. Each step uploads a
// file, previews (auto-detected column mapping), and confirms; the reconciliation step adds
// the computed-vs-actual delta report and an explicit "accept deltas" gate.
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  DEFAULT_OPTIONS,
  type ImportJob,
  type ImportOptions,
  type PreviewResponse,
  importsApi,
} from "@/lib/imports";

interface StepDef {
  key: string;
  title: string;
  blurb: string;
  optional?: boolean;
}

const STEPS: StepDef[] = [
  { key: "opening_balances", title: "Opening balances", blurb: "Set stock as of the period start. Products & warehouses must already exist; unmatched rows are rejected." },
  { key: "stock_replay", title: "Transaction replay", blurb: "Replay the period's movements (sale / receipt / transfer / adjustment / return) in one chronological timeline through the inventory engine." },
  { key: "stock_reconciliation", title: "Reconciliation", blurb: "Compare the computed stock to your actual physical count. A clean run has zero deltas; any difference must be accepted to post correcting adjustments." },
];

function num(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

export default function ReconstructionPage() {
  const [current, setCurrent] = useState(0);
  const [done, setDone] = useState<Record<string, ImportJob>>({});

  return (
    <div>
      <PageHeader
        title="Reconstruct Inventory History"
        description="From a clean base, set opening balances, replay the period's movements in order, then reconcile against your real counts. Nothing is committed until you confirm each step; the reconciliation gate blocks a mismatch unless you accept it."
      />

      <ol className="mb-5 flex flex-wrap gap-2">
        {STEPS.map((s, i) => {
          const state = done[s.key] ? "done" : i === current ? "active" : "todo";
          return (
            <li key={s.key}
              className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${
                state === "done" ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : state === "active" ? "border-brand-300 bg-brand-50 text-brand-700"
                  : "border-slate-200 bg-white text-slate-400"}`}>
              <span className={`flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold ${
                state === "done" ? "bg-emerald-500 text-white" : state === "active" ? "bg-brand-500 text-white" : "bg-slate-200 text-slate-500"}`}>
                {state === "done" ? "✓" : i + 1}
              </span>
              {s.title}
            </li>
          );
        })}
      </ol>

      <ReconStep
        key={STEPS[current].key}
        step={STEPS[current]}
        isLast={current === STEPS.length - 1}
        onComplete={(job) => {
          setDone((d) => ({ ...d, [STEPS[current].key]: job }));
          if (current < STEPS.length - 1) setCurrent(current + 1);
        }}
        onBack={current > 0 ? () => setCurrent(current - 1) : undefined}
      />
    </div>
  );
}

function ReconStep({ step, isLast, onComplete, onBack }: {
  step: StepDef; isLast: boolean; onComplete: (j: ImportJob) => void; onBack?: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [mapping, setMapping] = useState<Record<string, number | null>>({});
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [acceptDeltas, setAcceptDeltas] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isRecon = step.key === "stock_reconciliation";

  const options = (): ImportOptions => ({ ...DEFAULT_OPTIONS, accept_deltas: acceptDeltas });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const up = await importsApi.upload(step.key, file);
      const pv = await importsApi.preview(step.key, up.job_id, up.detected_mapping, options());
      return { up, pv };
    },
    onSuccess: ({ up, pv }) => { setJobId(up.job_id); setMapping(up.detected_mapping); setPreview(pv); setErr(null); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Upload failed."),
  });

  const revalidate = useMutation({
    mutationFn: () => importsApi.preview(step.key, jobId!, mapping, options()),
    onSuccess: (pv) => setPreview(pv),
  });

  const confirm = useMutation({
    mutationFn: () => importsApi.confirm(step.key, jobId!, mapping, options()),
    onSuccess: (job) => {
      if (job.status === "completed") onComplete(job);
      else { setErr("This step did not complete — resolve the issues below and retry."); void revalidate.mutate(); }
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Confirm failed."),
  });

  const recon = preview?.reconciliation ?? [];
  const hasDeltas = !!preview?.has_deltas;
  const canCommit = preview?.can_commit !== false;

  return (
    <Card className="p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-slate-800">{step.title}</h2>
        <p className="mt-1 text-sm text-slate-500">{step.blurb}</p>
      </div>

      {err && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => void importsApi.downloadTemplate(step.key, "basic")}>
          <Download className="h-4 w-4" /> Template
        </Button>
        <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
        <Button onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          <Upload className="h-4 w-4" /> {upload.isPending ? "Uploading…" : preview ? "Replace file" : "Upload file"}
        </Button>
        {onBack && <Button variant="ghost" onClick={onBack}>Back</Button>}
      </div>

      {preview && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-4 text-sm">
            <Stat label="Rows" value={preview.total_rows} />
            <Stat label="Valid" value={preview.valid_count} tone="ok" />
            <Stat label="With errors" value={preview.invalid_count} tone={preview.invalid_count ? "bad" : undefined} />
          </div>

          {preview.sample_errors.length > 0 && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-red-700">
                <AlertTriangle className="h-4 w-4" /> Rows to fix
              </div>
              <ul className="space-y-0.5 text-xs text-red-700">
                {preview.sample_errors.slice(0, 10).map((e) => (
                  <li key={e.row_number}>Row {e.row_number}: {e.errors.join("; ")}</li>
                ))}
              </ul>
            </div>
          )}

          {isRecon && recon.length > 0 && (
            <div className="overflow-hidden rounded-lg border border-slate-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-medium">Product</th>
                    <th className="px-3 py-2 font-medium">Warehouse</th>
                    <th className="px-3 py-2 text-right font-medium">Computed</th>
                    <th className="px-3 py-2 text-right font-medium">Actual</th>
                    <th className="px-3 py-2 text-right font-medium">Delta</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {recon.map((r, i) => (
                    <tr key={`${r.product}-${r.warehouse}-${i}`} className={r.delta !== 0 ? "bg-amber-50" : ""}>
                      <td className="px-3 py-1.5 font-mono text-[13px]">{r.product}</td>
                      <td className="px-3 py-1.5 text-slate-600">{r.warehouse}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{num(r.computed)}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{num(r.actual)}</td>
                      <td className={`px-3 py-1.5 text-right font-mono font-medium ${r.delta !== 0 ? "text-amber-700" : "text-emerald-600"}`}>
                        {r.delta > 0 ? `+${num(r.delta)}` : num(r.delta)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {isRecon && recon.length > 0 && !hasDeltas && (
            <div className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              <CheckCircle2 className="h-4 w-4" /> Clean reconciliation — every location matches. Nothing to adjust.
            </div>
          )}

          {isRecon && hasDeltas && (
            <label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              <input type="checkbox" className="mt-0.5" checked={acceptDeltas}
                onChange={(e) => { setAcceptDeltas(e.target.checked); setTimeout(() => revalidate.mutate(), 0); }} />
              <span>Accept these deltas and post correcting adjustments so the system matches the counted stock. This is recorded.</span>
            </label>
          )}

          <div className="flex items-center gap-2">
            <Button disabled={!canCommit || confirm.isPending || !jobId}
              onClick={() => { setErr(null); confirm.mutate(); }}>
              {confirm.isPending ? "Committing…" : isLast ? "Reconcile & finish" : "Confirm & continue"}
            </Button>
            {revalidate.isPending && <Spinner label="Rechecking…" />}
          </div>
        </div>
      )}
    </Card>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "ok" | "bad" }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-1.5">
      <span className="text-xs uppercase tracking-wide text-slate-400">{label}</span>
      <span className={`ml-2 font-semibold ${tone === "ok" ? "text-emerald-600" : tone === "bad" ? "text-red-600" : "text-slate-700"}`}>{value}</span>
    </div>
  );
}
