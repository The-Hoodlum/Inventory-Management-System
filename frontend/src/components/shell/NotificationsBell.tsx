// Notifications bell. Shows stored, event-driven notifications (bold until read) above the
// computed operational signals (low stock, pending approvals). The badge counts unread
// stored items plus live signals; clicking a stored item marks it read and jumps to where
// it's handled.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { notificationsApi, type NotificationSeverity } from "@/lib/notifications";
import { Popover } from "./Popover";

const DOT: Record<NotificationSeverity, string> = {
  info: "bg-brand-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
};

export function NotificationsBell() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: notificationsApi.list,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["notifications"] });
  const markRead = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: invalidate });
  const markAll = useMutation({ mutationFn: notificationsApi.markAllRead, onSuccess: invalidate });

  const items = data?.items ?? [];
  const signals = data?.signals ?? [];
  const badge = data?.badge_count ?? 0;
  const unread = data?.unread_count ?? 0;
  const empty = items.length === 0 && signals.length === 0;

  function go(href: string | null, close: () => void) {
    if (href) navigate(href);
    close();
  }

  return (
    <Popover
      align="right"
      width="w-80"
      trigger={
        <span className="relative flex h-9 w-9 items-center justify-center rounded-lg text-content-muted hover:bg-canvas hover:text-content">
          <Bell className="h-[18px] w-[18px]" />
          {badge > 0 && (
            <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
              {badge > 99 ? "99+" : badge}
            </span>
          )}
        </span>
      }
    >
      {(close) => (
        <div>
          <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
            <span className="text-sm font-semibold text-content">Notifications</span>
            {unread > 0 && (
              <button
                onClick={() => markAll.mutate()}
                disabled={markAll.isPending}
                className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-50"
              >
                Mark all read
              </button>
            )}
          </div>

          {empty ? (
            <div className="px-3 py-8 text-center text-sm text-content-subtle">You're all caught up.</div>
          ) : (
            <ul className="max-h-96 overflow-auto py-1">
              {/* Stored, event-driven notifications */}
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => {
                      if (!n.is_read) markRead.mutate(n.id);
                      go(n.href, close);
                    }}
                    className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-canvas ${n.is_read ? "" : "bg-brand-50/40"}`}
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.is_read ? "bg-line-strong" : DOT[n.severity]}`} />
                    <span className="min-w-0">
                      <span className={`block text-sm ${n.is_read ? "text-content-muted" : "font-medium text-content"}`}>{n.title}</span>
                      {n.body && <span className="block truncate text-xs text-muted">{n.body}</span>}
                    </span>
                  </button>
                </li>
              ))}

              {items.length > 0 && signals.length > 0 && (
                <li className="my-1 border-t border-line" aria-hidden="true" />
              )}

              {/* Computed operational signals (no read state) */}
              {signals.map((s) => (
                <li key={s.kind}>
                  <button
                    onClick={() => go(s.href, close)}
                    className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-canvas"
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[s.severity]}`} />
                    <span className="min-w-0">
                      <span className="block text-sm text-content">{s.title}</span>
                      {s.detail && <span className="block truncate text-xs text-muted">{s.detail}</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Popover>
  );
}
