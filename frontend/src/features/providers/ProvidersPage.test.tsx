import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { agent, models, skills, tools } from "../../test/fixtures";
import { ME, mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const OLLAMA = {
  name: "ollama", id: null, label: "Ollama (server)", kind: "ollama", builtin: true, base_url: null,
  has_secret: false, secret_hint: null, available: true, status: "ok", last_error: null, last_checked_at: null,
};
const OPENAI = {
  ...OLLAMA, name: "c-1", id: "c-1", label: "OpenAI", kind: "openai", builtin: false,
  has_secret: true, secret_hint: "…abcd", available: null, status: "unknown",
};
const CLOUD_MODELS = [
  { name: "gpt-x", size: null, supports_tools: null, supports_thinking: null, tools_source: null, context_window: 128000 },
];

describe("Providers page", () => {
  it("adds a provider with a write-only API key", async () => {
    let list: unknown[] = [OLLAMA];
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /providers": () => list,
      "POST /providers": () => {
        list = [OLLAMA, OPENAI];
        return OPENAI;
      },
    });
    renderApp("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Add provider" }));
    const form = screen.getByRole("form", { name: "Add provider" });
    await userEvent.type(within(form).getByLabelText(/^API key/), "sk-secret-abcd");
    await userEvent.click(within(form).getByRole("button", { name: "Save provider" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/providers")?.body).toEqual({
        name: "OpenAI",
        kind: "openai",
        base_url: null,
        api_key: "sk-secret-abcd",
      }),
    );
    // Listed with only the hint, never the key.
    expect(await screen.findByText(/key …abcd/)).toBeInTheDocument();
    expect(screen.queryByText(/sk-secret/)).toBeNull();
  });

  it("requires a base URL for OpenAI-compatible endpoints", async () => {
    mockApi({ "GET /health": HEALTH, "GET /providers": [OLLAMA] });
    renderApp("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Add provider" }));
    await userEvent.selectOptions(screen.getByLabelText("Type"), "openai_compatible");
    const save = screen.getByRole("button", { name: "Save provider" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Base URL/), "http://127.0.0.1:1234/v1");
    expect(save).toBeEnabled();
  });

  it("shows unknown tool support and runs the live check", async () => {
    let probed = false;
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /providers": [OLLAMA, OPENAI],
      "GET /providers/c-1/models": () =>
        probed ? [{ ...CLOUD_MODELS[0], supports_tools: true, tools_source: "probe" }] : CLOUD_MODELS,
      "POST /providers/c-1/models/gpt-x/probe": () => {
        probed = true;
        return { model: "gpt-x", supports_tools: true, detail: "The model called the tool" };
      },
    });
    renderApp("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Show models of OpenAI" }));
    const list = await screen.findByRole("list", { name: "Models of c-1" });
    expect(within(list).getByText("Unknown")).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("button", { name: "Check tools" }));
    expect(await within(list).findByText("Tools (checked)")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/providers/c-1/models/gpt-x/probe")).toBe(true);
  });

  it("hides management from non-admins", async () => {
    mockApi({
      "GET /health": HEALTH,
      "GET /auth/me": { ...ME, role: "editor" },
      "GET /providers": [OLLAMA, OPENAI],
    });
    renderApp("/providers");
    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add provider" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete OpenAI" })).toBeNull();
  });
});

describe("Agent builder provider selection", () => {
  it("switches provider, loads its models and saves the connection", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /skills": skills,
      "GET /tools": tools,
      "GET /providers": [OLLAMA, OPENAI],
      "GET /providers/ollama/models": models,
      "GET /providers/c-1/models": CLOUD_MODELS,
      "POST /agents": { ...agent, id: "a-new", provider: "openai", connection_id: "c-1" },
      "GET /agents/a-new": { ...agent, id: "a-new", provider: "openai", connection_id: "c-1" },
    });
    renderApp("/agents/new");
    await userEvent.type(await screen.findByLabelText(/^Name/), "Cloud helper");
    await userEvent.selectOptions(await screen.findByLabelText("Provider"), "c-1");
    expect(screen.queryByLabelText("Context window")).toBeNull(); // Ollama-only setting hidden
    await userEvent.click(await screen.findByRole("radio", { name: /gpt-x/ }));
    expect(screen.getByText("Tools: unknown")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create agent" }));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.path === "/agents");
      expect(post?.body).toMatchObject({ provider: "openai", connection_id: "c-1", model: "gpt-x" });
    });
  });
});
