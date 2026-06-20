import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { formatDate, formatMoney, formatQty, shortId, titleCase } from "@/lib/format";
import { openPurchaseOrderPdf, poApi, type ReceiptLineInput } from "@/lib/po";
import { useProducts, useSuppliers, useWarehouses } from "@/lib/refdata";
import type { POLine } from "@/types/api";

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export default function PurchaseOrderDetailPage() {
  const { id = "" } = useParams();
  const { hasPermission } = useAuth();
  const qc = useQueryClient();

  const { map: productMap } = useProducts();
  const { map: supplierMap } = useSuppliers();
  const { map: warehouseMap } = useWarehouses();

  const [err, setErr] = useState<string | null>(null);
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [qtys, setQtys] = useState<Record<string, string>>({});

  const poQuery = useQuery({
    queryKey: ["purchase-order", id],
    queryFn: () => poApi.get(id),
  });
  const eventsQuery = useQuery({
    queryKey: ["purchase-order-events", id],
    queryFn: () => poApi.events(id),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["purchase-order", id] });
    qc.invalidateQueries({ queryKey: ["purchase-order-events", id] });
    qc.invalidateQueries({ queryKey: ["purchase-orders"] });
  };

  const action = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      setErr(null);
      setRejectOpen(false);
      setRejectComment("");
      invalidate();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const receive = useMutation({
    mutationFn: (lines: ReceiptLineInput[]) => poApi.receive(id, lines),
    onSuccess: () => {
      setErr(null);
      setReceiveOpen(false);
      setQtys({});
      invalidate();
    },
    onError: (e) => setErr((e as Error).message),
  });

  const po = poQuery.data;

  const openReceive = (lines: POLine[]) => {
    const defaults: Record<string, string> = {};
    for (const ln of lines) {
      const remaining = Number(ln.remaining_qty);
      if (remaining > 0) defaults[ln.id] = ln.remaining_qty;
    }
    setQtys(defaults);
    setErr(null);
    setReceiveOpen(true);
  };

  const submitReceipt = () => {
    const lines: ReceiptLineInput[] = Object.entries(qtys)
      .filter(([, v]) => Number(v) > 0)
      .map(([line_id, quantity]) => ({ line_id, quantity }));
    if (lines.length === 0) {
      setErr("Enter a quantity on at least one line.");
      return;
    }
    receive.mutate(lines);
  };

  const busy = action.isPending || receive.isPending;

  const buttons = useMemo(() => {
    if (!po) return null;
    const s = po.status;
    const items: React.ReactNode[] = [];
    if (s === "draft" && hasPermission("po.create")) {
      items.push(
        <Button key="submit" disabled={busy} onClick={() => action.mutate(() => poApi.submit(id))}>
          Submit for approval
        </Button>
      );
    }
    if (s === "pending_approval" && hasPermission("po.approve")) {
      items.push(
        <Button key="approve" disabled={busy} onClick={() => action.mutate(() => poApi.approve(id))}>
          Approve
        </Button>,
        <Button key="reject" variant="secondary" disabled={busy} onClick={() => setRejectOpen(true)}>
          Reject
        </Button>
      );
    }
    if (s === "approved" && hasPermission("po.approve")) {
      items.push(
        <Button key="send" disabled={busy} onClick={() => action.mutate(() => poApi.send(id))}>
          Mark as sent
        </Button>
      );
    }
    if ((s === "sent" || s === "partially_received") && hasPermission("inventory.receive")) {
      items.push(
        <Button key="receive" disabled={busy} onClick={() => openReceive(po.lines)}>
          Receive goods
        </Button>
      );
    }
    if (["draft", "pending_approval", "approved"].includes(s) && hasPermission("po.update")) {
      items.push(
        <Button
          key="cancel"
          variant="ghost"
          disabled={busy}
          onClick={() => action.mutate(() => poApi.cancel(id))}
        >
          Cancel
        </Button>
      );
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [po, busy]);

  if (poQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner label="Loading purchase order…" />
      </div>
    );
  }
  if (poQuery.isError || !po) {
    return (
      <Card className="p-6 text-sm text-red-700">
        Couldn’t load this purchase order. {(poQuery.error as Error | null)?.message ?? ""}
      </Card>
    );
  }

  return (
    <div>
      <Link
        to="/purchase-orders"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" /> Purchase orders
      </Link>

      <PageHeader
        title={po.po_number}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => openPurchaseOrderPdf(id).catch((e) => setErr((e as Error).message))}
            >
              <FileDown className="h-4 w-4" /> PDF
            </Button>
            {buttons}
          </div>
        }
      />

      <div className="mb-4 flex items-center gap-3">
        <StatusBadge status={po.status} />
        <span className="text-sm text-slate-400">Ordered {formatDate(po.order_date)}</span>
      </div>

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Lines */}
        <Card className="overflow-hidden lg:col-span-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-medium">Product</th>
                <th className="px-4 py-2.5 text-right font-medium">Ordered</th>
                <th className="px-4 py-2.5 text-right font-medium">Received</th>
                <th className="px-4 py-2.5 text-right font-medium">Remaining</th>
                <th className="px-4 py-2.5 text-right font-medium">Unit cost</th>
                <th className="px-4 py-2.5 text-right font-medium">Line total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {po.lines.map((ln) => {
                const product = productMap.get(ln.product_id);
                return (
                  <tr key={ln.id}>
                    <td className="px-4 py-3 text-slate-700">
                      <div className="font-medium">{product?.name ?? shortId(ln.product_id)}</div>
                      {product?.sku && (
                        <div className="font-mono text-xs text-slate-400">{product.sku}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px]">
                      {formatQty(ln.ordered_qty)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px]">
                      {formatQty(ln.received_qty)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px] text-slate-600">
                      {formatQty(ln.remaining_qty)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px]">
                      {formatMoney(ln.unit_cost, po.currency)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[13px]">
                      {formatMoney(ln.line_total, po.currency)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-200 text-sm">
                <td className="px-4 py-2.5 text-slate-500" colSpan={5}>
                  Subtotal
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {formatMoney(po.subtotal, po.currency)}
                </td>
              </tr>
              <tr className="text-sm">
                <td className="px-4 py-1 text-slate-500" colSpan={5}>
                  Tax
                </td>
                <td className="px-4 py-1 text-right font-mono">
                  {formatMoney(po.tax, po.currency)}
                </td>
              </tr>
              <tr className="text-sm font-semibold">
                <td className="px-4 py-2.5 text-slate-700" colSpan={5}>
                  Total
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {formatMoney(po.total, po.currency)}
                </td>
              </tr>
            </tfoot>
          </table>
        </Card>

        {/* Summary + timeline */}
        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-slate-800">Details</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <Row label="Currency" value={po.currency} />
              <Row label="Expected" value={formatDate(po.expected_date)} />
              <Row
                label="Supplier"
                value={supplierMap.get(po.supplier_id)?.name ?? shortId(po.supplier_id)}
              />
              <Row
                label="Warehouse"
                value={warehouseMap.get(po.warehouse_id)?.name ?? shortId(po.warehouse_id)}
              />
              {po.approved_at && <Row label="Approved" value={formatDate(po.approved_at)} />}
            </dl>
            {po.notes && (
              <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-600">{po.notes}</p>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="text-sm font-semibold text-slate-800">Timeline</h2>
            {eventsQuery.isLoading ? (
              <div className="mt-3">
                <Spinner />
              </div>
            ) : (
              <ol className="mt-3 space-y-3">
                {(eventsQuery.data ?? []).map((ev) => (
                  <li key={ev.id} className="flex gap-3">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
                    <div>
                      <div className="text-sm font-medium text-slate-800">{titleCase(ev.action)}</div>
                      {ev.from_status && ev.to_status && (
                        <div className="text-xs text-slate-400">
                          {ev.from_status.replace(/_/g, " ")} → {ev.to_status.replace(/_/g, " ")}
                        </div>
                      )}
                      {ev.comment && <div className="text-xs text-slate-500">“{ev.comment}”</div>}
                      <div className="text-xs text-slate-400">{fmtDateTime(ev.created_at)}</div>
                    </div>
                  </li>
                ))}
                {(eventsQuery.data ?? []).length === 0 && (
                  <li className="text-sm text-slate-400">No events yet.</li>
                )}
              </ol>
            )}
          </Card>
        </div>
      </div>

      {receiveOpen && (
        <Modal
          title="Receive goods"
          onClose={() => setReceiveOpen(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setReceiveOpen(false)}>
                Cancel
              </Button>
              <Button onClick={submitReceipt} disabled={receive.isPending}>
                {receive.isPending ? "Receiving…" : "Confirm receipt"}
              </Button>
            </>
          }
        >
          <p className="mb-3 text-sm text-slate-500">
            Enter the quantity received now for each line. Remaining quantities are pre-filled.
          </p>
          <div className="space-y-2">
            {po.lines
              .filter((ln) => Number(ln.remaining_qty) > 0)
              .map((ln) => (
                <div key={ln.id} className="flex items-center justify-between gap-3">
                  <div className="text-sm text-slate-600">
                    <span className="font-medium text-slate-800">
                      {productMap.get(ln.product_id)?.name ?? shortId(ln.product_id)}
                    </span>{" "}
                    · remaining {formatQty(ln.remaining_qty)}
                  </div>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={qtys[ln.id] ?? ""}
                    onChange={(e) => setQtys((q) => ({ ...q, [ln.id]: e.target.value }))}
                    className="w-32 rounded-lg border border-slate-300 px-3 py-1.5 text-right font-mono text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                  />
                </div>
              ))}
            {po.lines.every((ln) => Number(ln.remaining_qty) <= 0) && (
              <p className="text-sm text-slate-400">All lines are fully received.</p>
            )}
          </div>
        </Modal>
      )}

      {rejectOpen && (
        <Modal
          title="Reject purchase order"
          onClose={() => setRejectOpen(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRejectOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => action.mutate(() => poApi.reject(id, rejectComment || undefined))}
                disabled={action.isPending}
              >
                {action.isPending ? "Rejecting…" : "Reject"}
              </Button>
            </>
          }
        >
          <label className="text-sm text-slate-500" htmlFor="reason">
            Reason (optional)
          </label>
          <textarea
            id="reason"
            value={rejectComment}
            onChange={(e) => setRejectComment(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            placeholder="e.g. prices need renegotiating"
          />
        </Modal>
      )}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className={mono ? "font-mono text-xs text-slate-700" : "text-slate-800"}>{value}</dd>
    </div>
  );
}
