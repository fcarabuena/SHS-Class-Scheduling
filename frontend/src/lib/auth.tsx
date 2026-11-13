"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, getToken, setToken, UNAUTHORIZED_EVENT } from "./api";
import type { School, User } from "./types";

type TokenResponse = { access_token: string; user: User };

type AuthState = {
  user: User | null;
  school: School | null;
  loading: boolean;
  canEdit: boolean;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { school_name: string; full_name: string; email: string; password: string }) => Promise<void>;
  logout: () => void;
  reloadSchool: () => Promise<School>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [school, setSchool] = useState<School | null>(null);
  const [loading, setLoading] = useState(true);

  const reloadSchool = useCallback(async () => {
    const fresh = await api<School>("/api/school");
    setSchool(fresh);
    return fresh;
  }, []);

  const startSession = useCallback(
    async (response: TokenResponse) => {
      setToken(response.access_token);
      await reloadSchool();
      setUser(response.user);
    },
    [reloadSchool],
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setSchool(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function restore() {
      if (getToken()) {
        try {
          const [me, mySchool] = await Promise.all([api<User>("/api/auth/me"), api<School>("/api/school")]);
          if (!cancelled) {
            setUser(me);
            setSchool(mySchool);
          }
        } catch {
          setToken(null);
        }
      }
      if (!cancelled) setLoading(false);
    }
    restore();
    // Wake a sleeping (free-tier) API while the user is still reading or typing.
    api("/api/health").catch(() => undefined);
    window.addEventListener(UNAUTHORIZED_EVENT, logout);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHORIZED_EVENT, logout);
    };
  }, [logout]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      school,
      loading,
      canEdit: user?.role === "admin" || user?.role === "scheduler",
      isAdmin: user?.role === "admin",
      login: async (email, password) =>
        startSession(await api<TokenResponse>("/api/auth/login", { method: "POST", body: { email, password } })),
      register: async (data) =>
        startSession(await api<TokenResponse>("/api/auth/register", { method: "POST", body: data })),
      logout,
      reloadSchool,
    }),
    [user, school, loading, startSession, logout, reloadSchool],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
