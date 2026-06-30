// FormLayout — the standard detail/record layout every module reuses: a header with
// title + status + actions, a tabbed main column, and a right rail of composable side
// panels (activity/timeline, related documents, attachments, notes). All slots are
// optional, so a simple record uses just `tabs` while a rich one fills the rail.
import { clsx } from "clsx";
import { ArrowLeft } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/ui";
import { Panel } from "./Panel";

export interface FormTab {
  key: string;
  label: string;
  content: ReactNode;
}

export interface FormLayoutProps {
  title: ReactNode;
  subtitle?: ReactNode;
  status?: string;
  actions?: ReactNode;
  tabs: FormTab[];
  defaultTab?: string;
  backTo?: { href: string; label: string };
  // Right-rail slots — render whatever a module needs.
  activity?: ReactNode;
  related?: ReactNode;
  attachments?: ReactNode;
  notes?: ReactNode;
}

export function SidePanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Panel className="p-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </Panel>
  );
}

export interface TimelineItem {
  title: ReactNode;
  time?: string;
  detail?: ReactNode;
  icon?: ReactNode;
}

export function Timeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) return <p className="text-sm text-content-subtle">No activity yet.</p>;
  return (
    <ol className="space-y-4">
      {items.map((it, i) => (
        <li key={i} className="relative flex gap-3">
          <div className="flex flex-col items-center">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-100 text-brand-700">
              {it.icon ?? <span className="h-1.5 w-1.5 rounded-full bg-brand-600" />}
            </span>
            {i < items.length - 1 && <span className="mt-1 w-px flex-1 bg-line" />}
          </div>
          <div className="pb-1">
            <div className="text-sm text-content">{it.title}</div>
            {it.detail && <div className="text-xs text-muted">{it.detail}</div>}
            {it.time && <div className="mt-0.5 text-2xs text-content-subtle">{it.time}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function FormLayout({
  title,
  subtitle,
  status,
  actions,
  tabs,
  defaultTab,
  backTo,
  activity,
  related,
  attachments,
  notes,
}: FormLayoutProps) {
  const [active, setActive] = useState(defaultTab ?? tabs[0]?.key);
  const current = tabs.find((t) => t.key === active) ?? tabs[0];
  const hasRail = Boolean(activity || related || attachments || notes);

  return (
    <div>
      {backTo && (
        <Link
          to={backTo.href}
          className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-content"
        >
          <ArrowLeft className="h-4 w-4" /> {backTo.label}
        </Link>
      )}

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight text-content">{title}</h1>
            {status && <StatusBadge status={status} />}
          </div>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>

      <div className={clsx("grid gap-5", hasRail ? "lg:grid-cols-[1fr_20rem]" : "grid-cols-1")}>
        <div>
          <div className="mb-4 flex gap-1 border-b border-line">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setActive(t.key)}
                className={clsx(
                  "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
                  active === t.key
                    ? "border-brand-600 text-brand-700"
                    : "border-transparent text-muted hover:text-content"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          {current?.content}
        </div>

        {hasRail && (
          <aside className="space-y-4">
            {activity && <SidePanel title="Activity">{activity}</SidePanel>}
            {related && <SidePanel title="Related documents">{related}</SidePanel>}
            {attachments && <SidePanel title="Attachments">{attachments}</SidePanel>}
            {notes && <SidePanel title="Notes">{notes}</SidePanel>}
          </aside>
        )}
      </div>
    </div>
  );
}
