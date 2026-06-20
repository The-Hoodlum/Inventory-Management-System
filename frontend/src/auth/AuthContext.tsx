import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, tokenStore } from "@/lib/api";
import type { CurrentUser, Tokens } from "@/types/api";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: Status;
  user: CurrentUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasPermission: (code: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);

  async function loadMe() {
    try {
      const me = await api.get<CurrentUser>("/auth/me");
      setUser(me);
      setStatus("authenticated");
    } catch {
      tokenStore.clear();
      setUser(null);
      setStatus("anonymous");
    }
  }

  useEffect(() => {
    if (tokenStore.getAccess()) {
      void loadMe();
    } else {
      setStatus("anonymous");
    }
    // If the API layer clears tokens (e.g. a failed refresh), drop to anonymous.
    return tokenStore.subscribe(() => {
      if (!tokenStore.getAccess()) {
        setUser(null);
        setStatus("anonymous");
      }
    });
  }, []);

  async function login(email: string, password: string) {
    const tokens = await api.post<Tokens>("/auth/login", { email, password }, false);
    tokenStore.set(tokens);
    await loadMe();
  }

  function logout() {
    // Best-effort server-side revocation of the refresh session; never block
    // the UI on it (and don't attach the access token / trigger a refresh).
    const refresh = tokenStore.getRefresh();
    if (refresh) {
      void api.post("/auth/logout", { refresh_token: refresh }, false).catch(() => {});
    }
    tokenStore.clear();
    setUser(null);
    setStatus("anonymous");
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      login,
      logout,
      hasPermission: (code: string) => !!user?.permissions.includes(code),
    }),
    [status, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
