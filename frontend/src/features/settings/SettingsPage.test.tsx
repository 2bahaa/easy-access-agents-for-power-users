import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ME, mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const MEMBERS = [
  { user_id: "u-1", email: "ada@example.com", name: "Ada", role: "owner", joined_at: "2026-11-15T10:00:00Z" },
  { user_id: "u-2", email: "bob@example.com", name: "Bob", role: "editor", joined_at: "2026-11-15T11:00:00Z" },
];

describe("Organization settings", () => {
  it("lists members and adds one", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /members": MEMBERS,
      "POST /members": { user_id: "u-3", email: "cy@example.com", name: "Cy", role: "viewer", joined_at: "" },
    });
    renderApp("/settings");
    expect(await screen.findByText("bob@example.com")).toBeInTheDocument();
    expect(screen.getByText("(you)")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Add an existing user/), "cy@example.com");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "viewer");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/members")?.body).toEqual({
        email: "cy@example.com",
        role: "viewer",
      }),
    );
  });

  it("creates an API key and shows the token exactly once", async () => {
    let keys: unknown[] = [];
    mockApi({
      "GET /health": HEALTH,
      "GET /members": MEMBERS,
      "GET /api-keys": () => keys,
      "POST /api-keys": () => {
        const key = { id: "k-1", name: "CI", prefix: "abcdef123456", role: "editor", user_id: "u-1", created_at: "", last_used_at: null, expires_at: null, revoked_at: null };
        keys = [key];
        return { ...key, token: "eaa_abcdef123456_secret" };
      },
    });
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("tab", { name: /API keys/ }));
    await userEvent.type(screen.getByLabelText("Key name"), "CI");
    await userEvent.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByTestId("new-api-key")).toHaveTextContent("eaa_abcdef123456_secret");
    // The list shows only the prefix.
    const list = await screen.findByText("eaa_abcdef123456_…");
    expect(within(list.closest("li")!).queryByText(/secret/)).toBeNull();
  });

  it("hides admin-only sections from editors", async () => {
    mockApi({
      "GET /health": HEALTH,
      "GET /auth/me": { ...ME, role: "editor", organizations: [{ ...ME.organizations[0], role: "editor" }] },
      "GET /members": MEMBERS,
    });
    renderApp("/settings");
    expect(await screen.findByRole("tab", { name: /Members/ })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Audit log/ })).toBeNull();
    expect(screen.queryByLabelText(/Add an existing user/)).toBeNull();
  });

  it("switches workspace and scopes later requests to it", async () => {
    const twoWorkspaces = {
      ...ME,
      organizations: [
        {
          ...ME.organizations[0],
          workspaces: [...ME.organizations[0]!.workspaces, { id: "w-2", org_id: "o-1", name: "Research", slug: "research-1" }],
        },
      ],
    };
    let current = "w-1";
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /auth/me": () => ({ ...twoWorkspaces, current_workspace_id: current }),
      "GET /members": MEMBERS,
    });
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("tab", { name: /Workspaces/ }));
    current = "w-2";
    await userEvent.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() => {
      const last = calls.filter((c) => c.path === "/auth/me").at(-1);
      expect(last?.headers.get("X-Workspace-Id")).toBe("w-2");
    });
    expect(await screen.findByText("current")).toBeInTheDocument();
  });
});
