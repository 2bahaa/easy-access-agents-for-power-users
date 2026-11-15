import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { WorkflowSpec } from "../../api/types";
import { WorkflowEditor } from "../../components/workflow/WorkflowEditor";
import { tools } from "../../test/fixtures";
import { mockApi, renderApp } from "../../test/render";
import { sseResponse, toSSE } from "../../test/stream";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const SPEC: WorkflowSpec = {
  schema_version: 1,
  nodes: [
    { id: "start", type: "start", label: "Start", config: { inputs: [{ name: "topic", description: "" }] }, position: { x: 0, y: 0 } },
    { id: "write", type: "llm", label: "Write", config: { provider: "ollama", model: "qwen3:4b", system: "", prompt: "About {{ input.topic }}" }, position: { x: 250, y: 0 } },
    { id: "end", type: "end", label: "End", config: { output: "{{ write }}" }, position: { x: 500, y: 0 } },
  ],
  edges: [
    { source: "start", target: "write", source_handle: null },
    { source: "write", target: "end", source_handle: null },
  ],
};
const CATALOGS = { agents: [], tools, collections: [], providers: [] };

describe("WorkflowEditor", () => {
  it("renders the graph, adds nodes from the palette and edits them", async () => {
    const onChange = vi.fn();
    render(<WorkflowEditor value={SPEC} onChange={onChange} catalogs={CATALOGS} />);
    expect(await screen.findByTestId("wf-node-write")).toHaveTextContent("Write");

    await userEvent.click(screen.getByRole("button", { name: "Add Condition node" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const added = onChange.mock.lastCall![0] as WorkflowSpec;
    expect(added.nodes.map((n) => n.id)).toEqual(["start", "write", "end", "condition"]);

    // The new node is selected: its settings are shown and editable.
    const settings = screen.getByRole("complementary", { name: "Node settings" });
    const expr = within(settings).getByLabelText(/^Expression/);
    await userEvent.clear(expr);
    await userEvent.type(expr, "len(write) > 10");
    await waitFor(() => {
      const spec = onChange.mock.lastCall![0] as WorkflowSpec;
      expect(spec.nodes.find((n) => n.id === "condition")?.config.expression).toBe("len(write) > 10");
    });

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const spec = onChange.mock.lastCall![0] as WorkflowSpec;
      expect(spec.nodes.find((n) => n.id === "condition")?.config.expression).not.toBe("len(write) > 10");
    });
  });

  it("configures a team node with members", async () => {
    const onChange = vi.fn();
    render(<WorkflowEditor value={SPEC} onChange={onChange} catalogs={{ ...CATALOGS, agents: [{ id: "ag-1", name: "Researcher" }] }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Add Team node" }));
    const settings = screen.getByRole("complementary", { name: "Node settings" });
    await userEvent.click(within(settings).getByRole("button", { name: "Add member" }));
    await userEvent.selectOptions(within(settings).getByLabelText("Member 1 agent"), "ag-1");
    await userEvent.type(within(settings).getByLabelText("Member 1 role"), "facts");
    await waitFor(() => {
      const spec = onChange.mock.lastCall![0] as WorkflowSpec;
      expect(spec.nodes.find((n) => n.type === "supervisor")?.config.members).toEqual([{ name: "member1", agent_id: "ag-1", role: "facts" }]);
    });
  });

  it("shows server problems on nodes and is read-only when asked", async () => {
    render(
      <WorkflowEditor
        value={SPEC}
        onChange={vi.fn()}
        catalogs={CATALOGS}
        readOnly
        problems={[{ node_id: "write", message: "Unknown model provider" }, { node_id: null, message: "Workflows cannot contain loops" }]}
      />,
    );
    expect(await screen.findByTestId("wf-node-write")).toHaveTextContent("Unknown model provider");
    expect(screen.getByRole("alert")).toHaveTextContent("loops");
    expect(screen.getByRole("button", { name: "Add LLM node" })).toBeDisabled();
  });
});

describe("Workflow pages", () => {
  it("creates a workflow from a template", async () => {
    const created = { id: "w-1", name: "Summarize, then translate", description: "", node_count: 3, updated_at: "", created_at: "", spec: SPEC };
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /workflows": [],
      "GET /workflow-templates": [{ id: "t", name: "Summarize, then translate", description: "Two steps", spec: SPEC }],
      "POST /workflows": created,
      "GET /workflows/w-1": created,
      "GET /agents": [],
      "GET /tools": tools,
      "GET /knowledge/collections": [],
      "GET /providers": [],
      "GET /workflows/w-1/runs": [],
      "GET /workflows/w-1/versions": [],
    });
    const { router } = renderApp("/workflows");
    await userEvent.click(await screen.findByRole("button", { name: "New workflow" }));
    await userEvent.click(await screen.findByRole("button", { name: /Summarize, then translate/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/workflows/w-1"));
    expect(calls.find((c) => c.method === "POST" && c.path === "/workflows")?.body).toMatchObject({ name: "Summarize, then translate", spec: SPEC });
    expect(await screen.findByLabelText("Workflow name", {}, { timeout: 5000 })).toHaveValue("Summarize, then translate");
  });

  it("runs the workflow and shows live node status and the output", async () => {
    const wf = { id: "w-1", name: "Flow", description: "", node_count: 3, updated_at: "", created_at: "", spec: SPEC };
    const events = [
      { type: "run.started", agent_id: null, model: null },
      { type: "node.started", node_id: "start", node_type: "start", label: "Start" },
      { type: "node.completed", node_id: "start", output: "topic: tides", duration_ms: 1 },
      { type: "node.started", node_id: "write", node_type: "llm", label: "Write" },
      { type: "node.completed", node_id: "write", output: "Tides are...", duration_ms: 20 },
      { type: "node.started", node_id: "end", node_type: "end", label: "End" },
      { type: "node.completed", node_id: "end", output: "Tides are...", duration_ms: 1 },
      { type: "run.completed", tool_call_count: 3, usage: {}, duration_ms: 30, output: "Tides are..." },
    ].map((e, i) => ({ ...e, run_id: "r-1", seq: i + 1, ts: "" }));
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /workflows/w-1": wf,
      "PUT /workflows/w-1": wf,
      "POST /workflows/validate": { valid: true, problems: [] },
      "POST /workflows/w-1/runs": { id: "r-1", status: "queued" },
      "GET /runs/r-1/stream?after=0": () => sseResponse(toSSE(events as never)),
      "GET /agents": [],
      "GET /tools": tools,
      "GET /knowledge/collections": [],
      "GET /providers": [],
      "GET /workflows/w-1/runs": [],
      "GET /workflows/w-1/versions": [],
    });
    renderApp("/workflows/w-1");
    await userEvent.type(await screen.findByLabelText("Input topic", {}, { timeout: 5000 }), "tides");
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Run" }));
    });
    expect(await screen.findByLabelText("Workflow output")).toHaveTextContent("Tides are...");
    expect(within(screen.getByLabelText("Run log")).getByText(/✓ write/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/workflows/w-1/runs" && c.method === "POST")?.body).toEqual({ inputs: { topic: "tides" } });
    expect(screen.getByTestId("wf-node-write")).toHaveTextContent("Tides are...");
  });
});
