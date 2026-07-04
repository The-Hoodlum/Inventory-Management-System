// Motorcycle bulk import — upload a spreadsheet of units, preview (rows ready / rows
// with errors / values needing a map-or-create decision / new reference values), map
// the unmatched values (status/model/colour, incl. splitting a batch token off a model),
// then commit all-or-nothing. Reuses the shared imports API; the motorcycle_units target
// is atomic, so nothing is half-created.
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeading, Panel } from "@/components/ds";
import { Button, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  type ColumnMapping,
  DEFAULT_OPTIONS,
  type ImportJob,
  type PreviewResponse,
  type ValueMap,
  type ValueResolution,
  importsApi,
} from "@/lib/imports";
import { statusLabel, UNIT_STATUSES, useMotoColours, useMotoModels } from "@/lib/motorcycles";

const KEY = "motorcycle_units";
const NEW = "__new__"; // sentinel select value for "create new"

type Choice = { action: "map" | "new"; target?: string; consignment?: string };

export default function MotorcycleImportPage() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const models = useMotoModels();
  const colours = useMotoColours();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping | null>(null);
  const [filename, setFilename] = useState<string>("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [createMissing, setCreateMissing] = useState(false);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [result, setResult] = useState<ImportJob | null>(null);

  const reset = () => {
    setJobId(null); setMapping(null); setPreview(null); setResult(null);
    setCreateMissing(false); setChoices({}); setErr(null); setFilename("");
    if (fileRef.current) fileRef.current.value = "";
  };

  const keyOf = (r: { kind: string; value: string }) => `${r.kind}::${r.value}`;

  // Seed a default choice per resolution the first time we see it (from the suggestion).
  function seed(resolutions: ValueResolution[]) {
    setChoices((prev) => {
      const next = { ...prev };
      for (const r of resolutions) {
        const k = keyOf(r);
        if (next[k]) continue;
        if (r.kind === "status") next[k] = { action: "map", target: r.suggestion ?? "assembled" };
        else if (r.suggestion) next[k] = { action: "map", target: r.suggestion, consignment: r.suggested_consignment ?? "" };
        else next[k] = { action: "new" };
      }
      return next;
    });
  }

  function toValueMaps(): ValueMap[] {
    return Object.entries(choices).map(([k, v]) => {
      const i = k.indexOf("::");
      const kind = k.slice(0, i) as ValueMap["kind"];
      const value = k.slice(i + 2);
      return {
        kind, value, action: v.action,
        target: v.action === "map" ? v.target : undefined,
        consignment: kind === "model" && v.action === "map" && v.consignment ? v.consignment : undefined,
      };
    });
  }

  async function runPreview(jid: string, map: ColumnMapping, create: boolean) {
    const p = await importsApi.preview(KEY, jid, map, {
      ...DEFAULT_OPTIONS, create_missing_references: create, value_maps: toValueMaps(),
    });
    setPreview(p);
    seed(p.value_resolutions ?? []);
  }

  async function onFile(file: File) {
    reset();
    setFilename(file.name);
    setBusy("Uploading…");
    setErr(null);
    try {
      const up = await importsApi.upload(KEY, file);
      setJobId(up.job_id);
      setMapping(up.detected_mapping);
      setBusy("Validating…");
      await runPreview(up.job_id, up.detected_mapping, false);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setBusy(null);
    }
  }

  async function recheck(create = createMissing) {
    if (!jobId || !mapping) return;
    setBusy("Re-checking…");
    setErr(null);
    try {
      await runPreview(jobId, mapping, create);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Re-check failed.");
    } finally {
      setBusy(null);
    }
  }

  async function commit() {
    if (!jobId || !mapping) return;
    setBusy("Importing…");
    setErr(null);
    try {
      const job = await importsApi.confirm(KEY, jobId, mapping, {
        ...DEFAULT_OPTIONS, create_missing_references: createMissing, value_maps: toValueMaps(),
      });
      setResult(job);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Import failed.");
    } finally {
      setBusy(null);
    }
  }

  const newRefs = preview?.new_references ?? [];
  const resolutions = preview?.value_resolutions ?? [];
  const hasErrors = (preview?.invalid_count ?? 0) > 0;
  const committable = !!preview && !hasErrors && (newRefs.length === 0 || createMissing);

  const setChoice = (k: string, patch: Partial<Choice>) =>
    setChoices((c) => ({ ...c, [k]: { ...c[k], ...patch } }));

  return (
    <div>
      <PageHeading
        title="Import motorcycles"
        description="Bulk-load the serialized unit registry from a spreadsheet. Validated all-or-nothing."
        icon={<FileSpreadsheet className="h-5 w-5" />}
        actions={<Button variant="secondary" onClick={() => navigate("/motorcycles")}>Back to units</Button>}
      />

      {err && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      {/* Step 1 — template + upload */}
      <Panel className="mb-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-content">1. Prepare your file</h3>
            <p className="mt-1 text-sm text-muted">
              Download the template, fill one row per unit (chassis, model, branch and status are
              required), then upload. CSV or Excel.
            </p>
          </div>
          <Button variant="secondary" onClick={() => void importsApi.downloadTemplate(KEY, "standard")}>
            <Download className="h-4 w-4" /> Template
          </Button>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f); }}
          />
          <Button onClick={() => fileRef.current?.click()} disabled={!!busy}>
            <Upload className="h-4 w-4" /> Choose file
          </Button>
          {filename && <span className="text-sm text-muted">{filename}</span>}
          {busy && <Spinner label={busy} />}
        </div>
      </Panel>

      {/* Step 2 — preview */}
      {preview && !result && (
        <Panel className="mb-4 p-5">
          <h3 className="mb-3 text-sm font-semibold text-content">2. Review</h3>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Rows" value={preview.total_rows} />
            <Stat label="Ready" value={preview.valid_count} tone="positive" />
            <Stat label="With errors" value={preview.invalid_count} tone={hasErrors ? "danger" : "default"} />
          </div>

          {preview.missing_required && preview.missing_required.length > 0 && (
            <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Unmapped required columns: {preview.missing_required.join(", ")}. Check your headers against the template.
            </p>
          )}

          {/* Value mapping — map unmatched status/model/colour values to existing ones */}
          {resolutions.length > 0 && (
            <div className="mt-4 rounded-lg border border-line bg-canvas p-3">
              <div className="text-sm font-medium text-content">
                {resolutions.length} value{resolutions.length === 1 ? "" : "s"} need a decision
              </div>
              <p className="mt-0.5 text-xs text-muted">
                Map each sheet value to an existing one (or create it). A model can shed a batch token into the unit’s consignment (e.g. “HLX 150 CONGO” → model “HLX 150” + consignment “CONGO”).
              </p>
              <div className="mt-3 space-y-2">
                {resolutions.map((r) => {
                  const k = keyOf(r);
                  const ch = choices[k] ?? { action: "new" as const };
                  return (
                    <div key={k} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="rounded-pill border border-line bg-surface px-2 py-0.5 text-xs text-content-subtle">{r.kind}</span>
                      <span className="font-mono text-[13px] text-content">{r.value}</span>
                      {r.count > 1 && <span className="text-xs text-content-subtle">×{r.count}</span>}
                      <span className="text-content-subtle">→</span>
                      {r.kind === "status" ? (
                        <select
                          className={SELECT}
                          value={ch.target ?? "assembled"}
                          onChange={(e) => setChoice(k, { action: "map", target: e.target.value })}
                        >
                          {UNIT_STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
                        </select>
                      ) : (
                        <>
                          <select
                            className={SELECT}
                            value={ch.action === "new" ? NEW : (ch.target ?? NEW)}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (v === NEW) setChoice(k, { action: "new", target: undefined });
                              else setChoice(k, { action: "map", target: v });
                            }}
                          >
                            {(r.kind === "model" ? (models.data?.items ?? []) : (colours.data?.items ?? [])).map((o) => (
                              <option key={o.id} value={o.name}>{o.name}</option>
                            ))}
                            {r.can_create && <option value={NEW}>➕ Create “{r.value}”</option>}
                          </select>
                          {r.kind === "model" && ch.action === "map" && (
                            <input
                              className={`${SELECT} w-36`}
                              placeholder="Consignment (optional)"
                              value={ch.consignment ?? ""}
                              onChange={(e) => setChoice(k, { consignment: e.target.value })}
                            />
                          )}
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
              <Button variant="secondary" className="mt-3" disabled={!!busy} onClick={() => void recheck()}>
                Apply mappings &amp; re-check
              </Button>
            </div>
          )}

          {newRefs.length > 0 && (
            <div className="mt-4 rounded-lg border border-line bg-canvas p-3">
              <div className="text-sm font-medium text-content">
                {newRefs.length} new reference value{newRefs.length === 1 ? "" : "s"} would be created
              </div>
              <p className="mt-0.5 text-xs text-muted">
                These are created only if you confirm — check for typos, or map them above instead.
              </p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {newRefs.map((n) => (
                  <li key={`${n.kind}:${n.value}`} className="rounded-pill border border-line bg-surface px-2 py-0.5 text-xs text-content-muted">
                    <span className="text-content-subtle">{n.kind}:</span> {n.value}
                    {n.count > 1 ? <span className="text-content-subtle"> ×{n.count}</span> : null}
                  </li>
                ))}
              </ul>
              <label className="mt-3 flex items-center gap-2 text-sm text-content">
                <input type="checkbox" checked={createMissing} onChange={(e) => { setCreateMissing(e.target.checked); void recheck(e.target.checked); }} />
                Create these {newRefs.length} new reference value{newRefs.length === 1 ? "" : "s"} on import
              </label>
            </div>
          )}

          {hasErrors && (
            <div className="mt-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-red-700">
                <AlertTriangle className="h-4 w-4" /> Resolve these rows — nothing imports while any row has an error. Mapping the values above clears “needs mapping” errors.
              </div>
              <div className="max-h-64 overflow-auto rounded-lg border border-line">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line bg-canvas text-left text-xs uppercase tracking-wide text-muted">
                      <th className="px-3 py-2 font-medium">Row</th>
                      <th className="px-3 py-2 font-medium">Chassis</th>
                      <th className="px-3 py-2 font-medium">Problem</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {preview.sample_errors.map((e) => (
                      <tr key={e.row_number} className="text-content-muted">
                        <td className="px-3 py-2">{e.row_number}</td>
                        <td className="px-3 py-2 font-mono text-[13px]">{e.sku ?? "—"}</td>
                        <td className="px-3 py-2 text-red-700">{e.errors.join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {jobId && (
                <Button variant="ghost" className="mt-2" onClick={() => void importsApi.downloadErrors(jobId)}>
                  <Download className="h-4 w-4" /> Download full error report
                </Button>
              )}
            </div>
          )}

          <div className="mt-5 flex items-center gap-2">
            <Button onClick={() => void commit()} disabled={!committable || !!busy}>
              {busy ? busy : `Import ${preview.valid_count} unit${preview.valid_count === 1 ? "" : "s"}`}
            </Button>
            <Button variant="secondary" onClick={reset} disabled={!!busy}>Start over</Button>
            {!committable && !hasErrors && newRefs.length > 0 && (
              <span className="text-xs text-muted">Confirm the new reference values above to continue.</span>
            )}
          </div>
        </Panel>
      )}

      {/* Step 3 — result */}
      {result && (
        <Panel className="p-5">
          {result.status === "completed" ? (
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" />
              <div>
                <h3 className="text-sm font-semibold text-content">Imported {result.imported_rows} units</h3>
                <p className="mt-1 text-sm text-muted">Every row committed successfully.</p>
                <div className="mt-3 flex gap-2">
                  <Link to="/motorcycles"><Button>View units</Button></Link>
                  <Button variant="secondary" onClick={reset}>Import another file</Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-red-600" />
              <div>
                <h3 className="text-sm font-semibold text-content">Nothing was imported</h3>
                <p className="mt-1 text-sm text-muted">
                  The batch was rejected ({result.error_count} issue{result.error_count === 1 ? "" : "s"}) and no
                  units were created. Download the report, fix the rows, and try again.
                </p>
                <div className="mt-3 flex gap-2">
                  <Button variant="secondary" onClick={() => void importsApi.downloadErrors(result.id)}>
                    <Download className="h-4 w-4" /> Error report
                  </Button>
                  <Button variant="secondary" onClick={reset}>Start over</Button>
                </div>
              </div>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

const SELECT =
  "rounded-lg border border-line bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

function Stat({ label, value, tone = "default" }: {
  label: string; value: number; tone?: "default" | "positive" | "danger";
}) {
  const toneClass = tone === "positive" ? "text-emerald-600" : tone === "danger" ? "text-red-600" : "text-content";
  return (
    <div className="rounded-lg border border-line bg-canvas p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
