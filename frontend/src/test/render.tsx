import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ToastProvider } from "../components/ui/Toast";
import { TooltipProvider } from "../components/ui/Tooltip";
import { routes } from "../routes";

/** Render the full app (real routes, fresh query cache) at a given URL. */
export function renderApp(url: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TooltipProvider>
          <RouterProvider router={router} />
        </TooltipProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...result, router, queryClient };
}

/** Mock `fetch` with a route table: { "GET /agents": body | (init) => body }. */
export function mockApi(routes: Record<string, unknown | ((init?: RequestInit) => unknown)>) {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "") + url.search;
    const method = init?.method ?? "GET";
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
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

export type { ReactElement };
