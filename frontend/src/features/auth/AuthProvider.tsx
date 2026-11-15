import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError } from "../../api/client";
import { refreshSession, session } from "../../api/session";
import type { Me } from "../../api/types";
import { AuthContext, type AuthState } from "./auth-context";

/** /auth/me; a remembered workspace the user lost access to falls back to the default. */
async function fetchMe(): Promise<Me> {
  try {
    return await api.me();
  } catch (error) {
    if (error instanceof ApiError && error.status === 403 && session.getWorkspaceId()) {
      session.setWorkspaceId(null);
      return api.me();
    }
    throw error;
  }
}

/**
 * Owns the signed-in state. On load it tries a silent refresh (httpOnly cookie) and reads
 * /auth/me; afterwards `authFetch` keeps the access token fresh and reports expiry here.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthState["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const loadMe = useCallback(async () => {
    const data = await fetchMe();
    session.setWorkspaceId(data.current_workspace_id);
    setMe(data);
    setStatus("authenticated");
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const ok = await refreshSession();
      if (cancelled) return;
      if (!ok) {
        setStatus("anonymous");
        return;
      }
      try {
        await loadMe();
      } catch {
        if (!cancelled) setStatus("anonymous");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadMe]);

  useEffect(
    () =>
      session.onExpired(() => {
        session.clear();
        setMe(null);
        setStatus("anonymous");
        queryClient.clear();
      }),
    [queryClient],
  );

  const value = useMemo<AuthState>(() => {
    const workspace =
      me?.organizations.flatMap((o) => o.workspaces).find((w) => w.id === me.current_workspace_id) ?? null;
    return {
      status,
      me,
      workspace,
      role: me?.role ?? null,
      async login(email, password) {
        const tokens = await api.login(email, password);
        session.setToken(tokens.access_token);
        queryClient.clear();
        await loadMe();
      },
      async register(email, password, name) {
        const tokens = await api.register(email, password, name);
        session.setToken(tokens.access_token);
        session.setWorkspaceId(null);
        queryClient.clear();
        await loadMe();
      },
      async logout() {
        try {
          await api.logout();
        } finally {
          session.clear();
          setMe(null);
          setStatus("anonymous");
          queryClient.clear();
        }
      },
      async switchWorkspace(workspaceId) {
        session.setWorkspaceId(workspaceId);
        queryClient.clear(); // never show one workspace's cached data in another
        await loadMe();
      },
      reload: loadMe,
    };
  }, [loadMe, me, queryClient, status]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
