import { createContext, useContext } from "react";

import type { Me, Role, Workspace } from "../../api/types";

export interface AuthState {
  status: "loading" | "anonymous" | "authenticated";
  me: Me | null;
  /** The workspace requests currently act on. */
  workspace: Workspace | null;
  role: Role | null;
  login(email: string, password: string): Promise<void>;
  register(email: string, password: string, name: string): Promise<void>;
  logout(): Promise<void>;
  switchWorkspace(workspaceId: string): Promise<void>;
  /** Re-read /auth/me (e.g. after creating a workspace). */
  reload(): Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

const RANK: Record<Role, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };

/** UI hint only — the backend enforces every permission. */
export function roleAtLeast(role: Role | null, required: Role): boolean {
  return role !== null && RANK[role] >= RANK[required];
}
