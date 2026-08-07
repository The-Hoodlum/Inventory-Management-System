import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "./AuthContext";

/**
 * Route-level permission gate. Renders its children only if the signed-in user holds
 * `permission`; otherwise redirects to the app launcher. Used so a role that can't see a
 * module in the sidebar also can't reach it by typing the URL (defence in depth — the API
 * enforces the same permission server-side).
 */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const { hasPermission } = useAuth();
  if (!hasPermission(permission)) {
    return <Navigate to="/apps" replace />;
  }
  return <>{children}</>;
}
