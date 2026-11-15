import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ToastProvider } from "../components/ui/Toast";
import { TooltipProvider } from "../components/ui/Tooltip";
import { AuthProvider } from "../features/auth/AuthProvider";
import { session } from "../api/session";
import { routes } from "../routes";

/** Render the full app (real routes, fresh query cache) at a given URL. */
export function renderApp(url: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <TooltipProvider>
            <RouterProvider router={router} />
          </TooltipProvider>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...result, router, queryClient };
}

export const ME = {
  user: { id: "u-1", email: "ada@example.com", name: "Ada" },
  organizations: [
    {
      id: "o-1",
      name: "Ada's organization",
      role: "owner",
      workspaces: [{ id: "w-1", org_id: "o-1", name: "Personal", slug: "personal-abc123" }],
    },
  ],
  current_workspace_id: "w-1",
  role: "owner",
};

/** Signed-in session defaults; a test can override any of them (e.g. refresh → 401). */
const AUTH_DEFAULTS: Record<string, unknown> = {
  "POST /auth/refresh": { access_token: "test-token", token_type: "bearer", expires_at: "2099-01-01T00:00:00Z" },
  "GET /auth/me": ME,
};

/** Mock `fetch` with a route table: { "GET /agents": body | (init) => body }.
 * The user is signed in unless the table overrides the auth routes. */
export function mockApi(userRoutes: Record<string, unknown | ((init?: RequestInit) => unknown)>) {
  const routes = { ...AUTH_DEFAULTS, ...userRoutes };
  session.setToken(null);
  const calls: Array<{ method: string; path: string; body: unknown; headers: Headers }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "") + url.search;
    const method = init?.method ?? "GET";
    const headers = new Headers(init?.headers);
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined, headers });
    const handler = routes[`${method} ${path}`];
    if (handler === undefined) {
      return new Response(JSON.stringify({ title: "Not found", detail: `No mock for ${method} ${path}` }), {
        status: 404,
      });
    }
    const body = typeof handler === "function" ? (handler as (i?: RequestInit) => unknown)(init) : handler;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), {
      status: method === "POST" ? 201 : 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

/** Signed in, but every data request fails at the network level (backend unreachable). */
export function mockApiDown() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    const key = `${init?.method ?? "GET"} ${path}`;
    if (key in AUTH_DEFAULTS) {
      return new Response(JSON.stringify(AUTH_DEFAULTS[key]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new TypeError("Failed to fetch");
  });
  session.setToken(null);
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

export type { ReactElement };
