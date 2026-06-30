// Notifications bell. Polls the existing operational-alerts endpoint and links each
// item to where it can be actioned. Badge shows the number of distinct alerts.
import { useQuery } from "@tanstack/react-query";
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
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: notificationsApi.list,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const items = data?.items ?? [];

  return (
    <Popover
      align="right"
      width="w-80"
      trigger={
        <span className="relative flex h-9 w-9 items-center justify-center rounded-lg text-content-muted hover:bg-canvas hover:text-content">
          <Bell className="h-[18px] w-[18px]" />
          {items.length > 0 && (
            <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
              {items.length}
            </span>
          )}
        </span>
      }
    >
      {(close) => (
        <div>
          <div className="border-b border-line px-3 py-2.5 text-sm font-semibold text-content">
            Notifications
          </div>
          {items.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-content-subtle">You’re all caught up.</div>
          ) : (
            <ul className="max-h-96 overflow-auto py-1">
              {items.map((n) => (
                <li key={n.kind}>
                  <button
                    onClick={() => {
                      navigate(n.href);
                      close();
                    }}
                    className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-canvas"
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[n.severity]}`} />
                    <span className="min-w-0">
                      <span className="block text-sm text-content">{n.title}</span>
                      {n.detail && <span className="block truncate text-xs text-muted">{n.detail}</span>}
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
