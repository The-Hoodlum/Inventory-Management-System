import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Button, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { catalogApi } from "@/lib/catalog";
import { formatQty } from "@/lib/format";
import { branchAvailability, orderRequestsApi, PURPOSES } from "@/lib/orderRequests";
import { useWarehouses } from "@/lib/refdata";

const INPUT =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";

interface DraftLine {
  product_id: string;
  sku: string;
  name: string;
  qty: string;
  remarks: string;
}

export function NewOrderRequestModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const warehouses = useWarehouses();

  // Branch users only request for the branch(es) they're scoped to (empty grants = all).
  const grants = user?.accessible_warehouse_ids ?? [];
  const branches = grants.length
    ? warehouses.list.filter((w) => grants.includes(w.id))
    : warehouses.list;

  const [branchId, setBranchId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [purpose, setPurpose] = useState(PURPOSES[0].value);
  const [comments, setComments] = useState("");
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Default to the first accessible branch once warehouses load.
  const effectiveBranch = branchId || branches[0]?.id || "";

  const avail = useQuery({
    queryKey: ["branch-availability", effectiveBranch],
    queryFn: () => branchAvailability(effectiveBranch),
    enabled: !!effectiveBranch,
    staleTime: 30_000,
  });

  // Server-side product search (works for catalogs far larger than the client can hold).
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
        branch_id: effectiveBranch,
        destination_branch_id: purpose === "branch_transfer" ? destinationId || null : null,
        purpose,
        comments: comments.trim() || null,
        lines: lines.map((l) => ({
          product_id: l.product_id,
          requested_qty: Number(l.qty),
          remarks: l.remarks.trim() || null,
        })),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["order-requests"] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not submit the request."),
  });

  function addLine(p: { id: string; sku: string; name: string }) {
    setLines((ls) => [...ls, { product_id: p.id, sku: p.sku, name: p.name, qty: "1", remarks: "" }]);
    setSearch("");
  }

  const isTransfer = purpose === "branch_transfer";
  const valid =
    !!effectiveBranch &&
    lines.length > 0 &&
    lines.every((l) => Number(l.qty) > 0) &&
    (!isTransfer || (!!destinationId && destinationId !== effectiveBranch));

  return (
    <Modal
      title="New order request"
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!valid || create.isPending} onClick={() => { setErr(null); create.mutate(); }}>
            {create.isPending ? "Submitting…" : "Submit request"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Branch</span>
            <select
              value={effectiveBranch}
              onChange={(e) => setBranchId(e.target.value)}
              className={`${INPUT} w-full`}
            >
              {branches.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Purpose</span>
            <select value={purpose} onChange={(e) => setPurpose(e.target.value)} className={`${INPUT} w-full`}>
              {PURPOSES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {isTransfer && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Destination location</span>
            <select
              value={destinationId}
              onChange={(e) => setDestinationId(e.target.value)}
              className={`${INPUT} w-full`}
            >
              <option value="">— choose destination —</option>
              {warehouses.list
                .filter((w) => w.id !== effectiveBranch)
                .map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
            </select>
          </label>
        )}

        <div>
          <span className="mb-1 block text-sm font-medium text-slate-700">Search inventory</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by item name or SKU"
            className={`${INPUT} w-full`}
          />
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
                    <button
                      key={p.id}
                      onClick={() => addLine(p)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50"
                    >
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
        </div>

        {lines.length > 0 && (
          <table className="w-full text-sm">
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
                      <input
                        type="number"
                        min={1}
                        value={l.qty}
                        onChange={(e) =>
                          setLines((ls) => ls.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))
                        }
                        className={`${INPUT} w-20 text-right`}
                      />
                    </td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                        className="text-slate-400 hover:text-red-600"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Comments (optional)</span>
          <textarea
            value={comments}
            onChange={(e) => setComments(e.target.value)}
            rows={2}
            className={`${INPUT} w-full`}
          />
        </label>
      </div>
    </Modal>
  );
}
