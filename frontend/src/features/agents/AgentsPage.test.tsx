import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { agent, models, skills, tools } from "../../test/fixtures";
import { mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };

describe("Agents pages (integration with mocked API)", () => {
  it("lists agents from the API and links to the editor", async () => {
    mockApi({
      "GET /health": HEALTH,
      "GET /agents": [
        {
          id: "a-1",
          name: "Research Assistant",
          description: "Reads my notes",
          provider: "ollama",
          model: "qwen3:4b",
          updated_at: new Date().toISOString(),
        },
      ],
    });
    renderApp("/agents");
    const card = await screen.findByRole("link", { name: "Research Assistant" });
    expect(screen.getByRole("link", { name: "Chat with Research Assistant" })).toHaveAttribute("href", "/agents/a-1/chat");
    expect(card).toHaveAttribute("href", "/agents/a-1");
    expect(screen.getByText("qwen3:4b")).toBeInTheDocument();
    expect(await screen.findByLabelText("Ollama: Online")).toBeInTheDocument();
  });

  it("shows an onboarding empty state", async () => {
    mockApi({ "GET /health": HEALTH, "GET /agents": [] });
    renderApp("/agents");
    expect(await screen.findByText("Create your first agent")).toBeInTheDocument();
  });

  it("shows a helpful error when the backend is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    renderApp("/agents");
    expect(await screen.findByText(/Cannot reach the backend/)).toBeInTheDocument();
    expect(await screen.findByLabelText("API: Offline")).toBeInTheDocument();
  });

  it("creates an agent and navigates to it", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /skills": skills,
      "GET /tools": tools,
      "GET /providers/ollama/models": models,
      "POST /agents": { ...agent, id: "a-new", name: "Helper", skills: [], tools: [] },
      "GET /agents/a-new": { ...agent, id: "a-new", name: "Helper", skills: [], tools: [] },
    });
    const { router } = renderApp("/agents/new");

    await userEvent.type(await screen.findByLabelText(/^Name/), "Helper");
    await userEvent.click(await screen.findByRole("radio", { name: /qwen3:4b/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/a-new"));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ name: "Helper", model: "qwen3:4b", provider: "ollama" });
    expect(await screen.findByText("Agent created")).toBeInTheDocument();
  });

  it("surfaces backend validation errors on save", async () => {
    mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": agent,
      "GET /skills": skills,
      "GET /tools": tools,
      "GET /providers/ollama/models": models,
      "PUT /agents/a-1": () =>
        new Response(
          JSON.stringify({ title: "Conflict", status: 409, detail: "Model 'qwen3:4b' does not support tool calling" }),
          { status: 409 },
        ),
    });
    renderApp("/agents/a-1");
    await userEvent.click(await screen.findByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("does not support tool calling");
  });

  it("deletes an agent after confirmation", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": agent,
      "GET /skills": skills,
      "GET /tools": tools,
      "GET /providers/ollama/models": models,
      "DELETE /agents/a-1": () => new Response(null, { status: 204 }),
      "GET /agents": [],
    });
    const { router } = renderApp("/agents/a-1");
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Delete this agent?");
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" }).at(-1)!);
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents"));
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/agents/a-1")).toBe(true);
  });
});
