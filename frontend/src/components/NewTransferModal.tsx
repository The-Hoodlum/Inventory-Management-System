import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Button, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { formatQty } from "@/lib/format";
import { branchAvailability, orderRequestsApi, PURPOSES } from "@/lib/orderRequests";
import { useBranches, useWarehouses } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

const STEPS = [
  "Source branch",
  "Source location",
  "Destination branch",
  "Destination location",
  "Transfer type",
  "Reason",
  "Products",
  "Review",
];

interface DraftLine {
  product_id: string;
  sku: string;
  name: string;
  qty: string;
}

export function NewTransferModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const branches = useBranches();
  const warehouses = useWarehouses();

  const grants = user?.accessible_warehouse_ids ?? [];
  const canUseLocation = (id: string) => grants.length === 0 || grants.includes(id);

  const [step, setStep] = useState(0);
  const [srcBranch, setSrcBranch] = useState("");
  const [srcLoc, setSrcLoc] = useState("");
  const [dstBranch, setDstBranch] = useState("");
  const [dstLoc, setDstLoc] = useState("");
  const [transferType, setTransferType] = useState("internal_transfer");
  const [reason, setReason] = useState("");
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Branches that hold at least one location the user may act on (source side).
  const sourceBranches = useMemo(() => {
    const usable = warehouses.list.filter((w) => w.is_active && canUseLocation(w.id));
    const ids = new Set(usable.map((w) => w.branch_id).filter(Boolean));
    return branches.list.filter((b) => b.is_active && ids.has(b.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branches.list, warehouses.list, grants]);
  const destBranches = branches.list.filter((b) => b.is_active);
  const srcLocations = warehouses.list.filter(
    (w) => w.is_active && w.branch_id === srcBranch && canUseLocation(w.id),
  );
  const dstLocations = warehouses.list.filter(
    (w) => w.is_active && w.branch_id === dstBranch && w.id !== srcLoc,
  );

  const avail = useQuery({
    queryKey: ["branch-availability", srcLoc],
    queryFn: () => branchAvailability(srcLoc),
    enabled: !!srcLoc,
    staleTime: 30_000,
  });

  const term = search.trim();
  const searchQ = useQuery({
    queryKey: ["product-search", term],
    queryFn: () => catalogApi.products({ search: term, page: 1, page_size: 8 }),
    enabled: term.length >= 2,
    placeholderData: (prev) => prev,
  });
  const added = new Set(lines.map((l) => l.product_id));
  const matches = (searchQ.data?.items ?? []).filter((p) => !added.has(p.id)).slice(0, 8);

  const create = useMutation({
    mutationFn: () =>
      orderRequestsApi.create({
        source_location_id: srcLoc,
        destination_location_id: dstLoc,
        purpose: transferType,
        comments: reason.trim(),
        submit: true,
        lines: lines.map((l) => ({ product_id: l.product_id, requested_qty: Number(l.qty) })),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["order-requests"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not submit the transfer."),
  });

  function addLine(p: { id: string; sku: string; name: string }) {
    setLines((ls) => [...ls, { product_id: p.id, sku: p.sku, name: p.name, qty: "1" }]);
    setSearch("");
  }

  const stepValid = (s: number): boolean => {
    switch (s) {
      case 0: return !!srcBranch;
      case 1: return !!srcLoc;
      case 2: return !!dstBranch;
      case 3: return !!dstLoc && dstLoc !== srcLoc;
      case 4: return !!transferType;
      case 5: return reason.trim().length > 0;
      case 6: return lines.length > 0 && lines.every((l) => Number(l.qty) > 0);
      default: return true;
    }
  };
  const allValid = [0, 1, 2, 3, 4, 5, 6].every(stepValid);
  const last = step === STEPS.length - 1;

  const branchName = (id: string) => branches.map.get(id)?.name ?? "—";
  const locName = (id: string) => warehouses.map.get(id)?.name ?? "—";
  const typeLabel = PURPOSES.find((p) => p.value === transferType)?.label ?? transferType;

  const next = () => {
    setErr(null);
    // Reset dependent selections when a parent changes.
    if (step === 0) setSrcLoc("");
    if (step === 2) setDstLoc("");
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  return (
    <Modal
      title="New stock transfer"
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          {step > 0 && (
            <Button variant="secondary" onClick={() => setStep((s) => s - 1)} disabled={create.isPending}>
              Back
            </Button>
          )}
          {!last ? (
            <Button onClick={next} disabled={!stepValid(step)}>Next</Button>
          ) : (
            <Button
              disabled={!allValid || create.isPending}
              onClick={() => { setErr(null); create.mutate(); }}
            >
              {create.isPending ? "Submitting…" : "Submit transfer"}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        {/* Stepper */}
        <ol className="flex flex-wrap gap-1.5 text-xs">
          {STEPS.map((label, i) => (
            <li
              key={label}
              className={`flex items-center gap-1 rounded-full px-2.5 py-1 ${
                i === step
                  ? "bg-brand-600 text-white"
                  : stepValid(i) && i < step
                    ? "bg-brand-50 text-brand-700"
                    : "bg-slate-100 text-slate-500"
              }`}
            >
              {stepValid(i) && i < step ? <Check className="h-3 w-3" /> : <span>{i + 1}</span>}
              {label}
            </li>
          ))}
        </ol>

        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        {step === 0 && (
          <Picker label="Select the source branch" value={srcBranch} onChange={(v) => { setSrcBranch(v); setSrcLoc(""); }}
            options={sourceBranches.map((b) => ({ value: b.id, label: b.name }))}
            empty="No branches available." />
        )}
        {step === 1 && (
          <Picker label={`Source location in ${branchName(srcBranch)}`} value={srcLoc} onChange={setSrcLoc}
            options={srcLocations.map((w) => ({ value: w.id, label: w.name }))}
            empty="No locations you can issue from in this branch." />
        )}
        {step === 2 && (
          <Picker label="Select the destination branch" value={dstBranch} onChange={(v) => { setDstBranch(v); setDstLoc(""); }}
            options={destBranches.map((b) => ({ value: b.id, label: b.name }))}
            empty="No branches available." />
        )}
        {step === 3 && (
          <Picker label={`Destination location in ${branchName(dstBranch)}`} value={dstLoc} onChange={setDstLoc}
            options={dstLocations.map((w) => ({ value: w.id, label: w.name }))}
            empty="No eligible destination locations (it can’t equal the source)." />
        )}
        {step === 4 && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Transfer type</span>
            <select value={transferType} onChange={(e) => setTransferType(e.target.value)} className={`${INPUT} w-full`}>
              {PURPOSES.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </label>
        )}
        {step === 5 && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Reason (required)</span>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
              className={`${INPUT} w-full`} autoFocus
              placeholder="Why is this stock being moved?" />
          </label>
        )}
        {step === 6 && (
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700">Search inventory</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by item name or SKU" className={`${INPUT} w-full`} />
            {term.length >= 2 && (
              <div className="mt-1 max-h-44 overflow-y-auto rounded-lg border border-slate-200">
                {searchQ.isFetching && matches.length === 0 ? (
                  <div className="p-3"><Spinner label="Searching…" /></div>
                ) : matches.length === 0 ? (
                  <div className="p-3 text-sm text-slate-400">No matching items.</div>
                ) : (
                  matches.map((p) => {
                    const have = avail.data?.get(p.id);
                    return (
                      <button key={p.id} onClick={() => addLine(p)}
                        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50">
                        <span>
                          <span className="font-medium text-slate-800">{p.name}</span>
                          <span className="ml-2 font-mono text-xs text-slate-400">{p.sku}</span>
                        </span>
                        <span className="flex items-center gap-2 text-xs text-slate-500">
                          Available: {have === undefined ? "—" : formatQty(have)}
                          <Plus className="h-3.5 w-3.5 text-brand-600" />
                        </span>
                      </button>
                    );
                  })
                )}
              </div>
            )}
            {lines.length > 0 && (
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2 font-medium">Item</th>
                    <th className="py-2 text-right font-medium">Available</th>
                    <th className="py-2 text-right font-medium">Qty</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {lines.map((l, i) => {
                    const have = avail.data?.get(l.product_id);
                    const over = have !== undefined && Number(l.qty) > have;
                    return (
                      <tr key={l.product_id}>
                        <td className="py-2">
                          <div className="font-medium text-slate-800">{l.name}</div>
                          <div className="font-mono text-xs text-slate-400">{l.sku}</div>
                        </td>
                        <td className="py-2 text-right font-mono text-xs text-slate-500">
                          {have === undefined ? "—" : formatQty(have)}
                        </td>
                        <td className="py-2 text-right">
                          <input type="number" min={1} value={l.qty}
                            onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))}
                            className={`${INPUT} w-20 text-right ${over ? "border-amber-400" : ""}`} />
                        </td>
                        <td className="py-2 text-right">
                          <button onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                            className="text-slate-400 hover:text-red-600">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
        {step === 7 && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1">
              <Review label="From" value={`${branchName(srcBranch)} → ${locName(srcLoc)}`} />
              <Review label="To" value={`${branchName(dstBranch)} → ${locName(dstLoc)}`} />
              <Review label="Type" value={typeLabel} />
              <Review label="Items" value={String(lines.length)} />
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-slate-600">
              <span className="font-medium text-slate-700">Reason: </span>{reason}
            </div>
            <table className="w-full">
              <tbody className="divide-y divide-slate-100">
                {lines.map((l) => (
                  <tr key={l.product_id}>
                    <td className="py-1.5">{l.name} <span className="font-mono text-xs text-slate-400">{l.sku}</span></td>
                    <td className="py-1.5 text-right font-mono">{l.qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}

function Picker({
  label, value, onChange, options, empty,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  empty: string;
}) {
  return (
    <div className="text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      {options.length === 0 ? (
        <div className="rounded-lg bg-slate-50 px-3 py-2 text-slate-400">{empty}</div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map((o) => (
            <button key={o.value} onClick={() => onChange(o.value)}
              className={`rounded-lg border px-3 py-2 text-left ${
                value === o.value
                  ? "border-brand-500 bg-brand-50 text-brand-800"
                  : "border-slate-200 hover:bg-slate-50"
              }`}>
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Review({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-400">{label}:</span>
      <span className="font-medium text-slate-700">{value}</span>
    </div>
  );
}
