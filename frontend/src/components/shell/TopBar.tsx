// Top navigation bar: mobile menu, tenant + branch selectors, the global-search trigger,
// theme toggle, AI assistant entry, notifications bell, and the user menu. Stateless —
// the AppShell owns the search/assistant overlays and passes open handlers down.
import { Menu, Search, Sparkles } from "lucide-react";

import { BranchSwitcher } from "./BranchSwitcher";
import { NotificationsBell } from "./NotificationsBell";
import { TenantSwitcher } from "./TenantSwitcher";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";

export function TopBar({
  onMenu,
  onOpenSearch,
  onOpenAssistant,
}: {
  onMenu: () => void;
  onOpenSearch: () => void;
  onOpenAssistant: () => void;
}) {
  return (
    <header className="flex h-16 items-center gap-2 border-b border-line bg-surface px-3 sm:px-4">
      <button
        onClick={onMenu}
        className="flex h-9 w-9 items-center justify-center rounded-lg text-content-muted hover:bg-canvas md:hidden"
        aria-label="Open menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      <TenantSwitcher />
      <div className="hidden sm:block">
        <BranchSwitcher />
      </div>

      {/* Global search trigger */}
      <button
        onClick={onOpenSearch}
        className="ml-auto flex w-full max-w-sm items-center gap-2 rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-content-subtle hover:border-strong md:ml-6 md:mr-auto"
      >
        <Search className="h-4 w-4" />
        <span className="flex-1 text-left">Search…</span>
        <kbd className="hidden rounded border border-line bg-surface px-1.5 py-0.5 text-2xs font-medium text-content-muted sm:block">
          ⌘K
        </kbd>
      </button>

      <div className="flex items-center gap-1">
        <ThemeToggle />
        <button
          onClick={onOpenAssistant}
          title="AI Assistant"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-content-muted hover:bg-canvas hover:text-content"
        >
          <Sparkles className="h-[18px] w-[18px]" />
        </button>
        <NotificationsBell />
        <UserMenu />
      </div>
    </header>
  );
}
