import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { mockApi, renderApp } from "../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const AGENTS = [
  { id: "a-1", name: "Research Assistant", description: "", provider: "ollama", model: "qwen3:4b", updated_at: new Date().toISOString() },
];
const CONVERSATIONS = [
  { id: "c-1", agent_id: "a-1", title: "Quarterly notes", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
];

function api() {
  return mockApi({
    "GET /health": HEALTH,
    "GET /agents": AGENTS,
    "GET /conversations": CONVERSATIONS,
    "GET /skills": [],
    "GET /tools": [],
    "GET /providers/ollama/models": [],
  });
}

describe("App shell", () => {
  it("redirects / to the overview and renders grouped navigation", async () => {
    api();
    const { router } = renderApp("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/overview"));
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByText("Build")).toBeInTheDocument();
    for (const label of ["Overview", "Agents", "Skills", "Tools"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("collapses the sidebar to a rail and remembers it", async () => {
    api();
    const user = userEvent.setup();
    renderApp("/agents");
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(localStorage.getItem("eaa.sidebar.collapsed")).toBe("1");
    // Rail links keep an accessible name even though the text is hidden.
    expect(screen.getByRole("link", { name: "Agents" })).toHaveAttribute("aria-label", "Agents");
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(localStorage.getItem("eaa.sidebar.collapsed")).toBe("0");
  });

  it("opens the command palette with Ctrl+K and navigates to an agent chat", async () => {
    api();
    const user = userEvent.setup();
    const { router } = renderApp("/agents");
    await user.keyboard("{Control>}k{/Control}");
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByRole("combobox"), "Research");
    await user.click(await within(dialog).findByRole("option", { name: /Research Assistant/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/a-1/chat"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("lists recent conversations in the palette", async () => {
    api();
    const user = userEvent.setup();
    const { router } = renderApp("/agents");
    await user.click(screen.getAllByRole("button", { name: /Search/ })[0]!);
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("option", { name: /Quarterly notes/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/a-1/chat/c-1"));
  });

  it("switches theme from the theme menu", async () => {
    api();
    const user = userEvent.setup();
    renderApp("/agents");
    await user.click(screen.getByRole("button", { name: "Theme: system" }));
    await user.click(await screen.findByRole("menuitem", { name: "Dark" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("eaa.theme")).toBe("dark");
  });
});
