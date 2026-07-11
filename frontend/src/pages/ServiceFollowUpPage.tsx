// Service Follow-up — the call-back list for sold bikes. For each sold unit we compute the
// next service due (time-only, scaled by how hard the bike is ridden: light/medium/heavy)
// from the sale date or the last logged service. Staff can log a service, set the usage
// profile, and (with config rights) edit the per-model schedule. Reads the serialized
// registry + an append-only service log; it never writes stock.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, PhoneCall, Plus, Settings2, Trash2, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Button, Card, Spinner, StatCard } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useMotoModels } from "@/lib/motorcycles";
import { useBranches } from "@/lib/refdata";
import {
  type DueStatus,
  type FollowUpRow,
  type ServiceUsage,
  USAGE_LABELS,
  serviceFollowupApi,
} from "@/lib/serviceFollowup";

const INPUT =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
const PAGE_SIZE = 25;

const STATUS_TABS: { key: DueStatus | ""; label: string }[] = [
  { key: "", label: "All" },
  { key: "overdue", label: "Overdue" },
  { key: "due_soon", label: "Due soon" },
  { key: "upcoming", label: "Upcoming" },
];

const USAGE_ORDER: ServiceUsage[] = ["light", "medium", "heavy"];

function dueBadge(row: FollowUpRow) {
  if (!row.status) return <span className="text-xs text-slate-400">No sale date</span>;
  const days = row.days_until_due ?? 0;
  const cls: Record<DueStatus, string> = {
    overdue: "bg-red-100 text-red-700",
    due_soon: "bg-amber-100 text-amber-800",
    upcoming: "bg-emerald-100 text-emerald-700",
  };
  const when =
    row.status === "overdue"
      ? `${Math.abs(days)}d overdue`
      : days === 0
        ? "due today"
        : `in ${days}d`;
  return (
    <span className={`inline-flex rounded-pill px-2 py-0.5 text-xs font-semibold ${cls[row.status]}`}>
      {when}
    </span>
  );
}

function bikeLabel(row: FollowUpRow): string {
  return [row.model_name ?? "—", row.colour_name].filter(Boolean).join(" · ");
}

export default function ServiceFollowUpPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("motorcycle.manage");
  const canConfig = hasPermission("motorcycle.config");
  const { list: branches } = useBranches();
  const models = useMotoModels();

  const [status, setStatus] = useState<DueStatus | "">("");
  const [branchId, setBranchId] = useState("");
  const [modelId, setModelId] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [logFor, setLogFor] = useState<FollowUpRow | null>(null);
  const [showSchedule, setShowSchedule] = useState(false);

  const { data, isFetching } = useQuery({
    queryKey: ["service-followup", status, branchId, modelId, search, page],
    queryFn: () =>
      serviceFollowupApi.list({
        status: status || undefined,
        branch_id: branchId || undefined,
        model_id: modelId || undefined,
        search: search || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (p) => p,
  });

  const kpis = data?.kpis;

  return (
    <div>
      <PageHeader
        title="Service Follow-up"
        description="When each sold bike is next due for service — computed from the sale date (or its last service) and how hard it's ridden. Call the customer back before they're overdue."
        actions={
          canConfig ? (
            <Button variant="secondary" onClick={() => setShowSchedule(true)}>
              <Settings2 className="h-4 w-4" /> Service schedule
            </Button>
          ) : undefined
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Overdue" value={kpis?.overdue ?? "—"} tone="danger" hint="Past the due date" />
        <StatCard label="Due soon" value={kpis?.due_soon ?? "—"} tone="warning" hint="Within 14 days" />
        <StatCard label="Upcoming" value={kpis?.upcoming ?? "—"} tone="positive" hint="Further out" />
        <StatCard label="Bikes tracked" value={kpis?.total ?? "—"} hint="Sold, with a sale date" />
      </div>

      <Card className="mb-4 space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key || "all"}
              onClick={() => {
                setStatus(t.key);
                setPage(1);
              }}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                status === t.key
                  ? "bg-brand-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {t.label}
            </button>
          ))}
          {isFetching && <Spinner />}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <input
            className={`${INPUT} w-auto flex-1 md:max-w-xs`}
            placeholder="Search customer, phone, chassis, plate…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          <select
            className={`${INPUT} w-auto`}
            value={branchId}
            onChange={(e) => {
              setBranchId(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All branches</option>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <select
            className={`${INPUT} w-auto`}
            value={modelId}
            onChange={(e) => {
              setModelId(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All models</option>
            {(models.data?.items ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {!data ? (
          <div className="flex h-40 items-center justify-center">
            <Spinner label="Loading…" />
          </div>
        ) : data.items.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-400">
            <CalendarClock className="mx-auto mb-2 h-6 w-6 text-slate-300" />
            No bikes match — sold bikes appear here once they have a sale date.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Customer</th>
                  <th className="px-4 py-2.5 font-medium">Bike</th>
                  <th className="px-4 py-2.5 font-medium">Sold</th>
                  <th className="px-4 py-2.5 font-medium">Usage</th>
                  <th className="px-4 py-2.5 text-center font-medium">Done</th>
                  <th className="px-4 py-2.5 font-medium">Next service</th>
                  <th className="px-4 py-2.5 font-medium">Due</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((row) => (
                  <FollowUpRowView
                    key={row.unit_id}
                    row={row}
                    canManage={canManage}
                    onLog={() => setLogFor(row)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div className="border-t border-slate-100 px-4 py-2">
            <Pagination
              page={data.page}
              totalPages={data.total_pages}
              total={data.total}
              onChange={setPage}
            />
          </div>
        )}
      </Card>

      {logFor && <LogServiceModal row={logFor} onClose={() => setLogFor(null)} />}
      {showSchedule && <ScheduleModal onClose={() => setShowSchedule(false)} />}
    </div>
  );
}

// ---- one row (usage is editable inline) -----------------------------------
function FollowUpRowView({
  row,
  canManage,
  onLog,
}: {
  row: FollowUpRow;
  canManage: boolean;
  onLog: () => void;
}) {
  const qc = useQueryClient();
  const setUsage = useMutation({
    mutationFn: (usage: ServiceUsage) => serviceFollowupApi.setUsage(row.unit_id, usage),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["service-followup"] }),
  });

  return (
    <tr className="align-top">
      <td className="px-4 py-3">
        <div className="font-medium text-slate-800">{row.customer_name ?? "—"}</div>
        {row.customer_phone && (
          <div className="flex items-center gap-1 text-xs text-slate-400">
            <PhoneCall className="h-3 w-3" /> {row.customer_phone}
          </div>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="font-medium text-slate-700">{bikeLabel(row)}</div>
        <div className="font-mono text-xs text-slate-400">{row.chassis_number}</div>
      </td>
      <td className="px-4 py-3 whitespace-nowrap text-slate-500">{formatDate(row.date_sold)}</td>
      <td className="px-4 py-3">
        {canManage ? (
          <select
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            value={row.service_usage}
            disabled={setUsage.isPending}
            onChange={(e) => setUsage.mutate(e.target.value as ServiceUsage)}
            title="How hard this bike is ridden — scales the service interval"
          >
            {USAGE_ORDER.map((u) => (
              <option key={u} value={u}>
                {USAGE_LABELS[u]}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-xs text-slate-500">{USAGE_LABELS[row.service_usage]}</span>
        )}
      </td>
      <td className="px-4 py-3 text-center font-mono text-slate-500">{row.services_done}</td>
      <td className="px-4 py-3">
        <div className="text-slate-700">{row.next_label ?? "—"}</div>
        <div className="text-xs text-slate-400">{formatDate(row.next_due_date)}</div>
      </td>
      <td className="px-4 py-3">{dueBadge(row)}</td>
      <td className="px-4 py-3 text-right">
        {canManage && (
          <Button variant="secondary" onClick={onLog}>
            <Wrench className="h-3.5 w-3.5" /> Log service
          </Button>
        )}
      </td>
    </tr>
  );
}

// ---- log a service --------------------------------------------------------
function LogServiceModal({ row, onClose }: { row: FollowUpRow; onClose: () => void }) {
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const records = useQuery({
    queryKey: ["service-followup", "records", row.unit_id],
    queryFn: () => serviceFollowupApi.listRecords(row.unit_id),
  });

  const save = useMutation({
    mutationFn: () =>
      serviceFollowupApi.logService(row.unit_id, { service_date: date, note: note || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["service-followup"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not log the service."),
  });

  return (
    <Modal
      title={`Log service — ${row.customer_name ?? row.chassis_number}`}
      size="md"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!date || save.isPending} onClick={() => { setErr(null); save.mutate(); }}>
            {save.isPending ? "Saving…" : `Record service #${row.next_sequence ?? row.services_done + 1}`}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {bikeLabel(row)} · <span className="font-mono">{row.chassis_number}</span> · usage{" "}
          {USAGE_LABELS[row.service_usage]}
        </div>
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Service date *</span>
          <input
            type="date"
            className={INPUT}
            value={date}
            max={today}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Note</span>
          <textarea
            className={INPUT}
            rows={2}
            placeholder="Work done, parts, odometer…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>

        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Service history
          </div>
          {!records.data ? (
            <Spinner label="Loading…" />
          ) : records.data.length === 0 ? (
            <p className="text-sm text-slate-400">No services logged yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
              {records.data.map((r) => (
                <li key={r.id} className="flex items-center justify-between px-3 py-1.5">
                  <span className="text-slate-600">
                    #{r.sequence} {r.label && <span className="text-slate-400">· {r.label}</span>}
                  </span>
                  <span className="text-slate-500">{formatDate(r.service_date)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  );
}

// ---- per-model service schedule -------------------------------------------
function ScheduleModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const models = useMotoModels();
  const plans = useQuery({ queryKey: ["service-followup", "plans"], queryFn: () => serviceFollowupApi.listPlans() });
  const [modelId, setModelId] = useState(""); // "" = tenant default
  const [stages, setStages] = useState<{ label: string; interval_days: number }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["service-followup"] });

  // Seed the editor from the stored plan (or the module default) whenever the model changes.
  const seed = useMemo(() => {
    if (!plans.data) return null;
    const stored =
      modelId === ""
        ? plans.data.plans.find((p) => p.model_id === null)
        : plans.data.plans.find((p) => p.model_id === modelId);
    const source = stored ?? plans.data.module_default;
    return source.stages.map((s) => ({ label: s.label, interval_days: s.interval_days }));
  }, [plans.data, modelId]);

  // Load seed into editable state once per model selection.
  if (seed && loaded !== modelId) {
    setStages(seed);
    setLoaded(modelId);
  }

  const save = useMutation({
    mutationFn: () =>
      serviceFollowupApi.upsertPlan({
        model_id: modelId || null,
        stages: stages.map((s) => ({ label: s.label || null, interval_days: s.interval_days })),
      }),
    onSuccess: () => {
      invalidate();
      void plans.refetch();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save the schedule."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => serviceFollowupApi.deletePlan(id),
    onSuccess: () => {
      invalidate();
      void plans.refetch();
    },
  });

  const currentStored =
    modelId === ""
      ? plans.data?.plans.find((p) => p.model_id === null)
      : plans.data?.plans.find((p) => p.model_id === modelId);

  const setStage = (i: number, patch: Partial<{ label: string; interval_days: number }>) =>
    setStages((s) => s.map((st, idx) => (idx === i ? { ...st, ...patch } : st)));
  const addStage = () =>
    setStages((s) => [...s, { label: `Service ${s.length + 1}`, interval_days: 90 }]);
  const removeStage = (i: number) => setStages((s) => s.filter((_, idx) => idx !== i));

  return (
    <Modal
      title="Service schedule"
      size="lg"
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Done
        </Button>
      }
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-500">
          Each stage's interval is the gap in days from the previous service (the first counts from the
          sale). The last stage repeats for every service after it. Heavy usage shortens these gaps,
          light usage stretches them. Models with no schedule use the default below.
        </p>
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Schedule for</span>
          <select className={INPUT} value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">Default (all models)</option>
            {(models.data?.items ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </label>

        <div className="rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">#</th>
                <th className="px-3 py-2 font-medium">Label</th>
                <th className="px-3 py-2 font-medium">Gap (days)</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {stages.map((s, i) => (
                <tr key={i}>
                  <td className="px-3 py-2 font-mono text-slate-400">{i + 1}</td>
                  <td className="px-3 py-2">
                    <input
                      className={INPUT}
                      value={s.label}
                      onChange={(e) => setStage(i, { label: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      min={1}
                      className={`${INPUT} w-24`}
                      value={s.interval_days}
                      onChange={(e) =>
                        setStage(i, { interval_days: Math.max(1, Number(e.target.value)) })
                      }
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {stages.length > 1 && (
                      <button
                        className="text-slate-400 hover:text-red-600"
                        onClick={() => removeStage(i)}
                        title="Remove stage"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-3 py-2">
            <button
              className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
              onClick={addStage}
            >
              <Plus className="h-3.5 w-3.5" /> Add stage
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button disabled={stages.length === 0 || save.isPending} onClick={() => { setErr(null); save.mutate(); }}>
            {save.isPending ? "Saving…" : "Save schedule"}
          </Button>
          {currentStored?.id && (
            <Button
              variant="secondary"
              disabled={remove.isPending}
              onClick={() => remove.mutate(currentStored.id as string)}
            >
              <Trash2 className="h-4 w-4" /> Reset to default
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
