// Notifications inbox — the full history of stored, event-driven notifications (assembly
// events today; more producers later). Filter all / unread, mark one or all read, and jump
// to where each is handled. The live operational signals live on the bell, not here.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { notificationsApi, type NotificationSeverity } from "@/lib/notifications";

const DOT: Record<NotificationSeverity, string> = {
  info: "bg-brand-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
};

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
  return formatDate(iso);
}

export default function NotificationsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["notifications-inbox", unreadOnly],
    queryFn: () => notificationsApi.listInbox(unreadOnly),
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["notifications-inbox"] });
    void qc.invalidateQueries({ queryKey: ["notifications"] });   // the bell
  };
  const markRead = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: invalidate });
  const markAll = useMutation({ mutationFn: notificationsApi.markAllRead, onSuccess: invalidate });

  const items = data?.items ?? [];
  const unread = data?.unread_count ?? 0;

  return (
    <div>
      <PageHeader
        title="Notifications"
        description="Events that need your attention — bikes sold before assembly, assembled and ready, or released for dispatch. Click one to act on it."
        actions={unread > 0 ? (
          <Button variant="secondary" disabled={markAll.isPending} onClick={() => markAll.mutate()}>
            Mark all read
          </Button>
        ) : undefined}
      />

      <div className="mb-4 flex items-center gap-2">
        {([["all", "All"], ["unread", "Unread"]] as const).map(([key, label]) => {
          const active = (key === "unread") === unreadOnly;
          return (
            <button
              key={key}
              onClick={() => setUnreadOnly(key === "unread")}
              className={`rounded-full px-3 py-1 text-sm font-medium transition ${
                active ? "bg-brand-600 text-white" : "bg-canvas text-content-muted hover:bg-surface"
              }`}
            >
              {label}{key === "unread" && unread > 0 ? ` (${unread})` : ""}
            </button>
          );
        })}
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner label="Loading…" /></div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-sm text-content-subtle">
            <BellOff className="mx-auto mb-2 h-6 w-6 text-content-subtle" />
            {unreadOnly ? "No unread notifications." : "No notifications yet."}
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {items.map((n) => (
              <li key={n.id}>
                <button
                  onClick={() => {
                    if (!n.is_read) markRead.mutate(n.id);
                    if (n.href) navigate(n.href);
                  }}
                  className={`flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-canvas ${n.is_read ? "" : "bg-brand-50/40"}`}
                >
                  <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${n.is_read ? "bg-line-strong" : DOT[n.severity]}`} />
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm ${n.is_read ? "text-content-muted" : "font-medium text-content"}`}>{n.title}</span>
                    {n.body && <span className="block text-xs text-muted">{n.body}</span>}
                  </span>
                  <span className="shrink-0 whitespace-nowrap text-xs text-content-subtle">{ago(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
