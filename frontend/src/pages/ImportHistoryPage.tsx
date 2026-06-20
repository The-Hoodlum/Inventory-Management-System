import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, RotateCcw, Undo2, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Button, Card, Spinner } from "@/components/ui";
import { importsApi, type ImportJob } from "@/lib/imports";

const PAGE_SIZE = 20;

const STATUS_TONE: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-700",
  rolled_back: "bg-slate-200 text-slate-600",
  failed: "bg-red-100 text-red-700",
  running: "bg-amber-100 text-amber-800",
  pending: "bg-slate-100 text-slate-600",
  cancelled: "bg-slate-200 text-slate-600",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize " +
        (STATUS_TONE[status] ?? "bg-slate-100 text-slate-700")
      }
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

export default function ImportHistoryPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading, isError, error: qErr } = useQuery({
    queryKey: ["imports", page],
    queryFn: () => importsApi.list(undefined, page, PAGE_SIZE),
    placeholderData: (prev) => prev,
  });

  async function act(job: ImportJob, kind: "rollback" | "retry") {
    const verb = kind === "rollback" ? "roll back" : "retry the failed rows of";
    if (!window.confirm(`Are you sure you want to ${verb} "${job.filename}"?`)) return;
    setBusyId(job.id);
    setError(null);
    try {
      if (kind === "rollback") await importsApi.rollback(job.id);
      else await importsApi.retry(job.id);
      await qc.invalidateQueries({ queryKey: ["imports"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Import History"
        description="Past data imports — download error reports, retry failed rows, or roll back."
        actions={
          <Button onClick={() => navigate("/import/inventory")}>
            <Upload className="h-4 w-4" /> New import
          </Button>
        }
      />

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6">
            <Spinner label="Loading imports…" />
          </div>
        ) : isError ? (
          <div className="p-6 text-sm text-red-700">
            {qErr instanceof Error ? qErr.message : "Failed to load imports"}
          </div>
        ) : data && data.items.length > 0 ? (
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 text-right font-medium">Total</th>
                <th className="px-4 py-2 text-right font-medium">Imported</th>
                <th className="px-4 py-2 text-right font-medium">Skipped</th>
                <th className="px-4 py-2 text-right font-medium">Errors</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((job) => {
                const canRollback = job.status === "completed";
                const hasErrors = job.error_count > 0;
                return (
                  <tr key={job.id} className="border-t border-slate-100">
                    <td className="px-4 py-2 text-slate-800">{job.filename}</td>
                    <td className="px-4 py-2 text-slate-500">
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2">
                      <StatusPill status={job.status} />
                    </td>
                    <td className="px-4 py-2 text-right tabular">{job.total_rows}</td>
                    <td className="px-4 py-2 text-right tabular text-emerald-700">{job.imported_rows}</td>
                    <td className="px-4 py-2 text-right tabular text-amber-700">{job.skipped_rows}</td>
                    <td className="px-4 py-2 text-right tabular text-red-700">{job.error_count}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center justify-end gap-1">
                        {hasErrors && (
                          <Button
                            variant="ghost"
                            className="px-2 py-1"
                            title="Download error report"
                            onClick={() => void importsApi.downloadErrors(job.id)}
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                        )}
                        {hasErrors && canRollback && (
                          <Button
                            variant="ghost"
                            className="px-2 py-1"
                            title="Retry failed rows"
                            disabled={busyId === job.id}
                            onClick={() => act(job, "retry")}
                          >
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                        )}
                        {canRollback && (
                          <Button
                            variant="ghost"
                            className="px-2 py-1 text-red-600"
                            title="Roll back this import"
                            disabled={busyId === job.id}
                            onClick={() => act(job, "rollback")}
                          >
                            <Undo2 className="h-4 w-4" />
                          </Button>
                        )}
                        {busyId === job.id && <Spinner />}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="p-8 text-center text-sm text-slate-500">
            No imports yet. <button className="text-brand-600 underline" onClick={() => navigate("/import/inventory")}>Start one</button>.
          </div>
        )}
      </Card>

      {data && (
        <Pagination
          page={page}
          totalPages={Math.ceil(data.total / PAGE_SIZE)}
          total={data.total}
          onChange={setPage}
        />
      )}
    </div>
  );
}
