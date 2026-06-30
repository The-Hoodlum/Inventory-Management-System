// Theme controller for the design system. Persists the user's choice and toggles
// the `.dark` class on <html>, which flips every semantic token (see index.css).
// "system" follows the OS preference and updates live.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePref = "light" | "dark" | "system";

const KEY = "ip.theme";

interface ThemeValue {
  pref: ThemePref;
  resolved: "light" | "dark";
  setPref: (p: ThemePref) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeValue | undefined>(undefined);

function systemDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function apply(resolved: "light" | "dark") {
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(
    () => (localStorage.getItem(KEY) as ThemePref | null) ?? "system"
  );
  const [systemIsDark, setSystemIsDark] = useState(systemDark);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystemIsDark(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const resolved: "light" | "dark" = pref === "system" ? (systemIsDark ? "dark" : "light") : pref;

  useEffect(() => {
    apply(resolved);
  }, [resolved]);

  const value = useMemo<ThemeValue>(
    () => ({
      pref,
      resolved,
      setPref: (p) => {
        localStorage.setItem(KEY, p);
        setPrefState(p);
      },
      toggle: () => {
        const next = resolved === "dark" ? "light" : "dark";
        localStorage.setItem(KEY, next);
        setPrefState(next);
      },
    }),
    [pref, resolved]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
