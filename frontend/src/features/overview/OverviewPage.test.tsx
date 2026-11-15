import { screen } from "@testing-library/react";

import { models, skills, tools } from "../../test/fixtures";
import { mockApi, mockApiDown, renderApp } from "../../test/render";

const now = new Date().toISOString();

describe("Overview page", () => {
  it("shows real counts, recent conversations and model support", async () => {
    mockApi({
      "GET /health": { status: "ok", database: "ok", ollama: "ok" },
      "GET /agents": [{ id: "a-1", name: "Helper", description: "", provider: "ollama", model: "qwen3:4b", updated_at: now }],
      "GET /skills": skills,
      "GET /tools": tools,
      "GET /conversations": [{ id: "c-1", agent_id: "a-1", title: "Budget questions", created_at: now, updated_at: now }],
      "GET /providers/ollama/models": models,
    });
    renderApp("/overview");
    expect(await screen.findByLabelText("Agents: 1")).toBeInTheDocument();
    expect(await screen.findByLabelText(`Skills: ${skills.length}`)).toBeInTheDocument();
    expect(await screen.findByLabelText(`Tools: ${tools.length}`)).toBeInTheDocument();
    expect(await screen.findByLabelText("Conversations: 1")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: /Budget questions/ });
    expect(link).toHaveAttribute("href", "/agents/a-1/chat/c-1");
    const toolCapable = models.filter((m) => m.supports_tools).length;
    expect(await screen.findByText(`${models.length} installed · ${toolCapable} support tools`)).toBeInTheDocument();
  });

  it("marks metrics unavailable instead of inventing numbers when the API is down", async () => {
    mockApiDown();
    renderApp("/overview");
    expect(await screen.findByLabelText("Agents: unavailable")).toBeInTheDocument();
    expect(await screen.findByText(/Conversations are unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Model list unavailable/)).toBeInTheDocument();
  });

  it("shows an empty state with no conversations", async () => {
    mockApi({
      "GET /health": { status: "ok", database: "ok", ollama: "ok" },
      "GET /agents": [],
      "GET /skills": [],
      "GET /tools": [],
      "GET /conversations": [],
      "GET /providers/ollama/models": [],
    });
    renderApp("/overview");
    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
  });
});
