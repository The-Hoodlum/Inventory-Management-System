// Active-branch context for the shell. The selected branch is persisted and exposed
// app-wide so every module can scope its TanStack Query keys/filters by branch
// (include `branchId` in the queryKey). "All branches" is represented by `null`.
//
// Driven by the existing /branches data (useBranches) — no new endpoint. The tenant
// is implicit in the auth token (one tenant per session); the top bar shows it and
// this context carries the per-branch selection that modules read.
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/auth/AuthContext";
import { useBranches } from "@/lib/refdata";
import type { Branch } from "@/types/api";

const KEY = "ip.branch";

interface BranchContextValue {
  branches: Branch[];
  branchId: string | null;
  branch: Branch | null;
  setBranchId: (id: string | null) => void;
  isLoading: boolean;
}

const BranchContext = createContext<BranchContextValue | undefined>(undefined);

export function BranchProvider({ children }: { children: ReactNode }) {
  const { list: allList, isLoading } = useBranches();
  const { user } = useAuth();

  // The switcher may only offer branches the user is allowed to see. An empty grant set
  // (owners/admins) = all branches. The server enforces this too — this just avoids
  // offering a branch that would be rejected.
  const allowed = user?.accessible_branch_ids ?? [];
  const list = useMemo(
    () => (allowed.length ? allList.filter((b) => allowed.includes(b.id)) : allList),
    [allList, allowed]
  );
  const map = useMemo(() => new Map(list.map((b) => [b.id, b])), [list]);

  const [branchId, setBranchIdState] = useState<string | null>(
    () => localStorage.getItem(KEY) || null
  );

  // Drop a selection the user can no longer see (stale, or now outside their scope).
  useEffect(() => {
    if (!isLoading && branchId && !map.has(branchId)) {
      setBranchIdState(null);
      localStorage.removeItem(KEY);
    }
  }, [isLoading, branchId, map]);

  const value = useMemo<BranchContextValue>(
    () => ({
      branches: list,
      branchId,
      branch: branchId ? map.get(branchId) ?? null : null,
      isLoading,
      setBranchId: (id) => {
        if (id) localStorage.setItem(KEY, id);
        else localStorage.removeItem(KEY);
        setBranchIdState(id);
      },
    }),
    [list, map, branchId, isLoading]
  );

  return <BranchContext.Provider value={value}>{children}</BranchContext.Provider>;
}

export function useBranchContext(): BranchContextValue {
  const ctx = useContext(BranchContext);
  if (!ctx) throw new Error("useBranchContext must be used within a BranchProvider");
  return ctx;
}
