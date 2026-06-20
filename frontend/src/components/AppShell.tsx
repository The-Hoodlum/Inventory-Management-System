import { LogOut } from "lucide-react";
import { Outlet } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Button } from "./ui";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  const { user, logout } = useAuth();
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-6">
          <div className="text-sm text-slate-500">{user?.roles.join(" · ") || "—"}</div>
          <div className="flex items-center gap-3">
            <div className="text-right leading-tight">
              <div className="text-sm font-medium text-slate-800">{user?.full_name}</div>
              <div className="text-xs text-slate-400">{user?.email}</div>
            </div>
            <Button variant="ghost" onClick={logout}>
              <LogOut className="h-4 w-4" /> Sign out
            </Button>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
