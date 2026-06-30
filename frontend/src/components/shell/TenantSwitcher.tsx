// Company/tenant selector. One tenant per session today (from the auth token), so this
// shows the active company and is built as a selector for future multi-tenant support.
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";

import { tenantApi } from "@/lib/tenantSettings";
import { Popover } from "./Popover";

export function TenantSwitcher() {
  const { data } = useQuery({ queryKey: ["tenant", "settings"], queryFn: tenantApi.get });
  const name = data?.brand_name || data?.company_name || "Workspace";
  const initial = name.charAt(0).toUpperCase();

  return (
    <Popover
      align="left"
      width="w-64"
      trigger={
        <span className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-canvas">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand-600 text-xs font-bold text-white">
            {initial}
          </span>
          <span className="max-w-[10rem] truncate text-sm font-semibold text-content">{name}</span>
          <ChevronDown className="h-4 w-4 text-content-subtle" />
        </span>
      }
    >
      {() => (
        <div className="p-1">
          <div className="px-2 py-1.5 text-2xs font-semibold uppercase tracking-wide text-content-subtle">
            Company
          </div>
          <div className="flex items-center justify-between rounded-lg px-2 py-2 text-sm hover:bg-canvas">
            <span className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded bg-brand-600 text-2xs font-bold text-white">
                {initial}
              </span>
              <span className="truncate text-content">{name}</span>
            </span>
            <Check className="h-4 w-4 text-brand-600" />
          </div>
          {data?.industry && (
            <div className="px-2 pb-1.5 pt-1 text-xs text-content-subtle">{data.industry}</div>
          )}
        </div>
      )}
    </Popover>
  );
}
