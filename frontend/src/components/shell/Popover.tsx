// Tiny click-away popover used across the top bar (branch switcher, bell, user menu).
// No external dependency: an invisible full-screen button closes it on outside click.
import { clsx } from "clsx";
import { useState, type ReactNode } from "react";

export function Popover({
  trigger,
  children,
  align = "right",
  width = "w-72",
}: {
  trigger: ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  width?: string;
}) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex items-center">
        {trigger}
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-hidden
            className="fixed inset-0 z-40 cursor-default"
            onClick={close}
          />
          <div
            className={clsx(
              "absolute z-50 mt-2 rounded-card border border-line bg-elevated text-content shadow-pop",
              width,
              align === "right" ? "right-0" : "left-0"
            )}
          >
            {children(close)}
          </div>
        </>
      )}
    </div>
  );
}
