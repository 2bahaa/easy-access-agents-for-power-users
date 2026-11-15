/**
 * Client-side auth session.
 *
 * - The access token lives only in memory (never localStorage), so injected scripts cannot
 *   read a long-lived credential from storage. The refresh token is an httpOnly cookie
 *   scoped to /api/auth that JavaScript cannot read at all.
 * - `authFetch` attaches `Authorization` and `X-Workspace-Id`; on a 401 it refreshes once
 *   (single-flight) and retries, otherwise it reports the session as expired.
 */

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api";

const WORKSPACE_KEY = "eaa.workspace";

let accessToken: string | null = null;
let workspaceId: string | null = readStoredWorkspace();
let refreshing: Promise<boolean> | null = null;
const expiredListeners = new Set<() => void>();

function readStoredWorkspace(): string | null {
  try {
    return localStorage.getItem(WORKSPACE_KEY);
  } catch {
    return null;
  }
}

export const session = {
  getToken: () => accessToken,
  setToken(token: string | null) {
    accessToken = token;
  },
  getWorkspaceId: () => workspaceId,
  setWorkspaceId(id: string | null) {
    workspaceId = id;
    try {
      if (id) localStorage.setItem(WORKSPACE_KEY, id);
      else localStorage.removeItem(WORKSPACE_KEY);
    } catch {
      /* non-persistent is fine */
    }
  },
  /** Subscribe to "session lost" (refresh failed); returns an unsubscribe function. */
  onExpired(listener: () => void) {
    expiredListeners.add(listener);
    return () => {
      expiredListeners.delete(listener);
    };
  },
  /** Forget everything (sign-out). */
  clear() {
    accessToken = null;
  },
};

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_BASE_URL}/auth/refresh`, { method: "POST", credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) {
        accessToken = null;
        return false;
      }
      const body = (await response.json()) as { access_token: string };
      accessToken = body.access_token;
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function withAuth(init: RequestInit): RequestInit {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (workspaceId) headers.set("X-Workspace-Id", workspaceId);
  return { ...init, headers, credentials: "same-origin" };
}

// Endpoints that handle credentials themselves: a 401 there is an answer, not an expiry.
const CREDENTIAL_ENDPOINTS = /\/auth\/(login|register|refresh|logout)$/;

export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(url, withAuth(init));
  if (response.status !== 401 || CREDENTIAL_ENDPOINTS.test(url)) return response;
  if (await refreshSession()) return fetch(url, withAuth(init));
  expiredListeners.forEach((listener) => listener());
  return response;
}
