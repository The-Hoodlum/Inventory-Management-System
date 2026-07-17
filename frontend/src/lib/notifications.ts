// Notifications client for the shell's bell. Merges two streams from GET /notifications:
// stored, event-driven notifications (with personal read/unread state) and computed
// operational signals (low stock, pending approvals — always "live", no read state).
import { api } from "@/lib/api";

export type NotificationSeverity = "info" | "warning" | "critical";

// A stored, event-driven notification for the current user.
export interface StoredNotification {
  id: string;
  event_type: string;
  severity: NotificationSeverity;
  title: string;
  body: string | null;
  href: string | null;
  entity_type: string | null;
  entity_id: string | null;
  is_read: boolean;
  created_at: string;
}

// A computed operational signal (recomputed each poll; no read state).
export interface OperationalSignal {
  kind: string;
  severity: NotificationSeverity;
  title: string;
  detail: string | null;
  count: number;
  href: string;
}

export interface NotificationsResponse {
  unread_count: number;   // unread stored notifications
  badge_count: number;    // unread stored + number of live signals
  items: StoredNotification[];
  signals: OperationalSignal[];
}

export const notificationsApi = {
  list: () => api.get<NotificationsResponse>("/notifications"),
  // Full inbox: more items, optionally unread-only.
  listInbox: (unreadOnly = false) =>
    api.get<NotificationsResponse>(`/notifications?limit=100${unreadOnly ? "&unread_only=true" : ""}`),
  markRead: (id: string) => api.post<NotificationsResponse>(`/notifications/${id}/read`),
  markAllRead: () => api.post<NotificationsResponse>("/notifications/read-all"),
};
