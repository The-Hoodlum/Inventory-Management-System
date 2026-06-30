// The application shell: collapsible sidebar + top bar + routed content, plus the
// global-search palette (⌘/Ctrl-K) and the AI assistant slide-over. All chrome is
// token-themed (light/dark) and wired to existing data (tenant, branches, alerts, search).
import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { BranchProvider } from "@/lib/branchContext";
import { AssistantPanel } from "./shell/AssistantPanel";
import { GlobalSearch } from "./shell/GlobalSearch";
import { Sidebar } from "./shell/Sidebar";
import { TopBar } from "./shell/TopBar";

const COLLAPSE_KEY = "ip.sidebar.collapsed";

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);

  const toggleCollapse = () =>
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      return !c;
    });

  // ⌘K / Ctrl-K opens global search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <BranchProvider>
    <div className="flex h-full bg-canvas">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={toggleCollapse}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          onMenu={() => setMobileOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
          onOpenAssistant={() => setAssistantOpen(true)}
        />
        <main className="min-h-0 flex-1 overflow-auto p-4 sm:p-6">
          <Outlet />
        </main>
      </div>

      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
      <AssistantPanel open={assistantOpen} onClose={() => setAssistantOpen(false)} />
    </div>
    </BranchProvider>
  );
}
