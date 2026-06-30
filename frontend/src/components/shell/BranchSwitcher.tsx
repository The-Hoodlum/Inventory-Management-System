// Branch selector. Drives the app-wide active branch (see BranchProvider), which every
// module reads to scope its data. Backed by the existing /branches data.
import { Check, ChevronDown, GitBranch } from "lucide-react";

import { useBranchContext } from "@/lib/branchContext";
import { Popover } from "./Popover";

export function BranchSwitcher() {
  const { branches, branchId, branch, setBranchId, isLoading } = useBranchContext();
  const label = isLoading ? "Loading…" : branch?.name ?? "All branches";

  return (
    <Popover
      align="left"
      width="w-64"
      trigger={
        <span className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-sm text-content-muted hover:bg-canvas">
          <GitBranch className="h-4 w-4 text-content-subtle" />
          <span className="max-w-[9rem] truncate">{label}</span>
          <ChevronDown className="h-4 w-4 text-content-subtle" />
        </span>
      }
    >
      {(close) => (
        <div className="max-h-80 overflow-auto p-1">
          <div className="px-2 py-1.5 text-2xs font-semibold uppercase tracking-wide text-content-subtle">
            Branch
          </div>
          <BranchRow
            label="All branches"
            active={!branchId}
            onClick={() => {
              setBranchId(null);
              close();
            }}
          />
          {branches.map((b) => (
            <BranchRow
              key={b.id}
              label={b.name}
              code={b.code}
              active={branchId === b.id}
              onClick={() => {
                setBranchId(b.id);
                close();
              }}
            />
          ))}
        </div>
      )}
    </Popover>
  );
}

function BranchRow({
  label,
  code,
  active,
  onClick,
}: {
  label: string;
  code?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center justify-between rounded-lg px-2 py-2 text-left text-sm text-content-muted hover:bg-canvas"
    >
      <span className="flex items-center gap-2 truncate">
        <span className="truncate text-content">{label}</span>
        {code && <span className="text-2xs text-content-subtle">{code}</span>}
      </span>
      {active && <Check className="h-4 w-4 shrink-0 text-brand-600" />}
    </button>
  );
}
