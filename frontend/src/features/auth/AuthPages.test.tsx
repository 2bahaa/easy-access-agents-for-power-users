import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ME, mockApi, renderApp } from "../../test/render";

const TOKEN = { access_token: "t", token_type: "bearer", expires_at: "2099-01-01T00:00:00Z" };

function signedOut(extra: Record<string, unknown> = {}) {
  // A fresh 401 Response per call (bodies can only be read once).
  return mockApi({
    ...extra,
    "POST /auth/refresh": () => new Response(JSON.stringify({ detail: "Not signed in" }), { status: 401 }),
  });
}

describe("auth pages", () => {
  it("sends signed-out users to the login page and back after signing in", async () => {
    let signedIn = false;
    const { calls } = mockApi({
      "POST /auth/refresh": () => new Response("{}", { status: 401 }),
      "POST /auth/login": () => {
        signedIn = true;
        return TOKEN;
      },
      "GET /auth/me": () => (signedIn ? ME : new Response("{}", { status: 401 })),
      "GET /health": { status: "ok", database: "ok", ollama: "ok" },
      "GET /skills": [],
    });
    const { router } = renderApp("/skills");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.search).toBe("?next=%2Fskills");

    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/skills"));
    const login = calls.find((c) => c.path === "/auth/login");
    expect(login?.body).toEqual({ email: "ada@example.com", password: "correct horse battery" });
    // Subsequent API calls carry the token.
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/skills")?.headers.get("Authorization")).toBe("Bearer t"),
    );
  });

  it("shows the server's error for bad credentials", async () => {
    signedOut({
      "POST /auth/login": () =>
        new Response(JSON.stringify({ title: "Unauthorized", detail: "Invalid email or password" }), { status: 401 }),
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("ignores off-site redirect targets after login", async () => {
    let signedIn = false;
    mockApi({
      "POST /auth/refresh": () => new Response("{}", { status: 401 }),
      "POST /auth/login": () => {
        signedIn = true;
        return TOKEN;
      },
      "GET /auth/me": () => (signedIn ? ME : new Response("{}", { status: 401 })),
      "GET /health": { status: "ok", database: "ok", ollama: "ok" },
      "GET /agents": [],
      "GET /skills": [],
      "GET /tools": [],
      "GET /conversations": [],
      "GET /providers/ollama/models": [],
    });
    const { router } = renderApp("/login?next=//evil.example.com");
    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/overview"));
  });

  it("registers with client-side password guidance", async () => {
    let registered = false;
    const { calls } = mockApi({
      "POST /auth/refresh": () => new Response("{}", { status: 401 }),
      "POST /auth/register": () => {
        registered = true;
        return TOKEN;
      },
      "GET /auth/me": () => (registered ? ME : new Response("{}", { status: 401 })),
      "GET /health": { status: "ok", database: "ok", ollama: "ok" },
      "GET /agents": [],
      "GET /skills": [],
      "GET /tools": [],
      "GET /conversations": [],
      "GET /providers/ollama/models": [],
    });
    const { router } = renderApp("/register");
    await userEvent.type(await screen.findByLabelText(/^Email/), "ada@example.com");
    await userEvent.type(screen.getByLabelText(/^Password/), "short");
    expect(screen.getByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Password/), "-and-long-now");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/overview"));
    expect(calls.find((c) => c.path === "/auth/register")?.body).toMatchObject({ email: "ada@example.com" });
  });
});
