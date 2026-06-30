// User profile menu: identity, roles, theme choice, and sign out.
import { LogOut, Monitor, Moon, Sun } from "lucide-react";

import { useAuth } from "@/auth/AuthContext";
import { useTheme, type ThemePref } from "@/lib/theme";
import { Popover } from "./Popover";

const THEME_OPTIONS: { value: ThemePref; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export function UserMenu() {
  const { user, logout } = useAuth();
  const { pref, setPref } = useTheme();
  const initials = (user?.full_name ?? "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <Popover
      align="right"
      width="w-64"
      trigger={
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
          {initials}
        </span>
      }
    >
      {(close) => (
        <div className="p-1">
          <div className="px-3 py-2">
            <div className="truncate text-sm font-semibold text-content">{user?.full_name}</div>
            <div className="truncate text-xs text-muted">{user?.email}</div>
            {user?.roles?.length ? (
              <div className="mt-1 text-2xs text-content-subtle">{user.roles.join(" · ")}</div>
            ) : null}
          </div>
          <div className="my-1 border-t border-line" />
          <div className="px-2 py-1 text-2xs font-semibold uppercase tracking-wide text-content-subtle">
            Theme
          </div>
          <div className="flex gap-1 px-2 pb-1">
            {THEME_OPTIONS.map((o) => {
              const Icon = o.icon;
              return (
                <button
                  key={o.value}
                  onClick={() => setPref(o.value)}
                  className={`flex flex-1 flex-col items-center gap-1 rounded-lg border px-2 py-1.5 text-2xs ${
                    pref === o.value
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-line text-content-muted hover:bg-canvas"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {o.label}
                </button>
              );
            })}
          </div>
          <div className="my-1 border-t border-line" />
          <button
            onClick={() => {
              close();
              logout();
            }}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-content-muted hover:bg-canvas"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </Popover>
  );
}
