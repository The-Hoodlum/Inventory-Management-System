// A small pill showing where a motorcycle sits on the assembly axis (independent of its
// sale status): 🟢 Assembled / 🟡 Assembly required / 🟠 Awaiting assembly (sold, owed).
import { ASSEMBLY_BADGE, assemblyState } from "@/lib/motorcycles";

export function AssemblyBadge({
  unit,
  className = "",
}: {
  unit: { assembled_date: string | null; assembly_pending: boolean };
  className?: string;
}) {
  const b = ASSEMBLY_BADGE[assemblyState(unit)];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${b.cls} ${className}`}
    >
      <span aria-hidden>{b.dot}</span>
      {b.label}
    </span>
  );
}
