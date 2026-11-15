import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { agent, models, skills, tools } from "../../test/fixtures";
import { mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const OLLAMA = {
  name: "ollama", id: null, label: "Ollama (server)", kind: "ollama", builtin: true, base_url: null,
  has_secret: false, secret_hint: null, available: true, status: "ok", last_error: null, last_checked_at: null,
};
const BASE = {
  "GET /health": HEALTH,
  "GET /skills": skills,
  "GET /tools": tools,
  "GET /providers": [OLLAMA],
  "GET /providers/ollama/models": models,
};
const TEMPLATES = [
  {
    id: "calculator-helper", name: "Calculation helper", description: "Exact numbers.", category: "Productivity",
    system_prompt: "Always use the calculator.", tools: [{ name: "calculator", config: {} }],
    model_params: { temperature: 0 }, max_tool_calls: 6, run_timeout_s: 120, suggested_skills: [],
  },
];

describe("Agent lifecycle in the editor", () => {
  it("shows the publish status and publishes with a note", async () => {
    let published = false;
    const { calls } = mockApi({
      ...BASE,
      "GET /agents/a-1": () => ({ ...agent, published_version: published ? 1 : null, has_unpublished_changes: !published }),
      "POST /agents/a-1/publish": () => {
        published = true;
        return { version: 1, note: "first", created_by: "u-1", created_at: new Date().toISOString() };
      },
      "GET /agents/a-1/versions": [],
    });
    renderApp("/agents/a-1");
    expect(await screen.findByText("Draft · not published")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = screen.getByRole("dialog", { name: "Publish agent" });
    await userEvent.type(within(dialog).getByLabelText(/Release note/), "first");
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/agents/a-1/publish")?.body).toEqual({ note: "first" }));
    expect(await screen.findByText("Published v1")).toBeInTheDocument();
  });

  it("compares a version with the draft and restores it", async () => {
    const v1 = { ...agent, system_prompt: "Old instructions." };
    const { calls } = mockApi({
      ...BASE,
      "GET /agents/a-1": { ...agent, published_version: 1, has_unpublished_changes: true },
      "GET /agents/a-1/versions": [{ version: 1, note: "launch", created_by: null, created_at: new Date().toISOString() }],
      "GET /agents/a-1/versions/1": {
        version: 1, note: "launch", created_by: null, created_at: "",
        write_config: {
          name: v1.name, description: v1.description, provider: "ollama", connection_id: null, model: v1.model,
          model_params: v1.model_params, system_prompt: v1.system_prompt, skill_ids: ["s-cite"],
          tools: v1.tools, max_tool_calls: v1.max_tool_calls, run_timeout_s: v1.run_timeout_s,
        },
      },
      "POST /agents/a-1/versions/1/restore": { ...agent, system_prompt: "Old instructions." },
    });
    renderApp("/agents/a-1");
    expect(await screen.findByText("v1 live · unpublished changes")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Version history" }));
    const sheet = await screen.findByRole("dialog", { name: "Version history" });
    await userEvent.click(await within(sheet).findByRole("button", { name: "Compare" }));
    const diff = await within(sheet).findByLabelText("Changes since v1");
    expect(within(diff).getByText("Instructions")).toBeInTheDocument();
    expect(within(diff).getByText("Old instructions.")).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("button", { name: "Restore to draft" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/agents/a-1/versions/1/restore")).toBe(true));
  });

  it("duplicates an agent", async () => {
    const { router } = renderWithDuplicate();
    await userEvent.click(await screen.findByRole("button", { name: "Duplicate agent" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/a-2"));
  });
});

function renderWithDuplicate() {
  mockApi({
    ...BASE,
    "GET /agents/a-1": { ...agent, published_version: null, has_unpublished_changes: true },
    "POST /agents/a-1/duplicate": { ...agent, id: "a-2", name: "Copy of Research Assistant" },
    "GET /agents/a-2": { ...agent, id: "a-2", name: "Copy of Research Assistant" },
  });
  return renderApp("/agents/a-1");
}

describe("Creating and importing agents", () => {
  it("starts a new agent from a template", async () => {
    mockApi({ ...BASE, "GET /agents": [], "GET /agent-templates": TEMPLATES });
    const { router } = renderApp("/agents");
    await userEvent.click(await screen.findByRole("button", { name: "New agent" }));
    const dialog = screen.getByRole("dialog", { name: "New agent" });
    await userEvent.click(await within(dialog).findByRole("link", { name: /Calculation helper/ }));
    await waitFor(() => expect(router.state.location.search).toBe("?template=calculator-helper"));
    expect(await screen.findByDisplayValue("Calculation helper")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Always use the calculator.")).toBeInTheDocument();
  });

  it("imports an agent from a JSON file", async () => {
    const { calls } = mockApi({
      ...BASE,
      "GET /agents": [],
      "POST /agents/import": { agent_id: "a-9", created_skills: ["cite"], reused_skills: [] },
      "GET /agents/a-9": { ...agent, id: "a-9" },
    });
    const { router } = renderApp("/agents");
    const doc = { format: "eaa.agent/v1", agent: { name: "Imported", model: "qwen3:4b" }, skills: [] };
    const input = await screen.findByLabelText("Import agent from JSON");
    fireEvent.change(input, { target: { files: [new File([JSON.stringify(doc)], "a.agent.json", { type: "application/json" })] } });
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/a-9"));
    expect(calls.find((c) => c.path === "/agents/import")?.body).toEqual(doc);
  });

  it("reports an invalid import file", async () => {
    mockApi({ ...BASE, "GET /agents": [] });
    renderApp("/agents");
    const input = await screen.findByLabelText("Import agent from JSON");
    fireEvent.change(input, { target: { files: [new File(["{not json"], "bad.json")] } });
    expect(await screen.findByText("The file is not valid JSON.")).toBeInTheDocument();
  });
});

describe("Skills v2", () => {
  const skill = {
    id: "s-1", slug: "tone", name: "Tone", description: "", is_builtin: false, category: "writing", tags: ["style"],
    version: 2, updated_at: "2026-11-15T10:00:00Z", created_at: "2026-11-15T10:00:00Z", content_md: "Current",
  };

  it("edits tags and shows version history with restore", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /skills": [skill],
      "GET /skills/s-1": skill,
      "GET /skill-templates": [],
      "PUT /skills/s-1": { ...skill, tags: ["style", "voice"] },
      "GET /skills/s-1/versions": [{ version: 1, name: "Tone", description: "", content_md: "Old body", created_by: null, created_at: "2026-11-14T10:00:00Z" }],
      "POST /skills/s-1/versions/1/restore": { ...skill, content_md: "Old body", version: 3 },
    });
    renderApp("/skills/s-1");
    const tags = await screen.findByLabelText(/^Tags/);
    await userEvent.clear(tags);
    await userEvent.type(tags, "Style, voice");
    await userEvent.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ tags: ["style", "voice"], category: "writing" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "v2" }));
    const history = await screen.findByRole("region", { name: "Skill history" });
    expect(await within(history).findByText("Old body")).toBeInTheDocument();
    await userEvent.click(within(history).getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/skills/s-1/versions/1/restore")).toBe(true));
  });

  it("imports a Markdown skill", async () => {
    const md = "---\nslug: tone\nname: Tone\n---\nBody";
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /skills": [],
      "POST /skills/import": skill,
      "GET /skills/s-1": skill,
      "GET /skill-templates": [],
    });
    const { router } = renderApp("/skills");
    const input = await screen.findByLabelText("Import skill from Markdown");
    fireEvent.change(input, { target: { files: [new File([md], "tone.md", { type: "text/markdown" })] } });
    await waitFor(() => expect(router.state.location.pathname).toBe("/skills/s-1"));
    expect(calls.find((c) => c.path === "/skills/import")?.body).toEqual({ markdown: md });
  });
});
