// Notifications client for the shell's bell. Surfaces existing operational signals
// (low stock, pending approvals) from /assistant/notifications, gated per-permission.
import { api } from "@/lib/api";

export type NotificationSeverity = "info" | "warning" | "critical";

export interface Notification {
  kind: string;
  severity: NotificationSeverity;
  title: string;
  detail: string | null;
  count: number;
  href: string;
}

export interface NotificationsResponse {
  total: number;
  items: Notification[];
}

export const notificationsApi = {
  list: () => api.get<NotificationsResponse>("/assistant/notifications"),
};
