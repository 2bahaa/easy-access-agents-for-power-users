import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { mockApi, mockApiDown, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const now = new Date().toISOString();
const daily = Array.from({ length: 7 }, (_, i) => ({
  date: `2026-11-${10 + i}`,
  runs: i === 6 ? 2 : 0,
  failed: 0,
  tokens: i === 6 ? 60 : 0,
}));
const SUMMARY = {
  days: 7,
  runs: 2,
  by_status: { completed: 1, failed: 1 },
  by_kind: { agent: 1, workflow: 1 },
  success_rate: 0.5,
  tool_calls: 3,
  input_tokens: 40,
  output_tokens: 20,
  runs_without_usage: 0,
  avg_duration_ms: 1500,
  p95_duration_ms: 2400,
  daily,
  top_agents: [{ agent_id: "a-1", name: "Calc", runs: 1, failed: 0 }],
  top_tools: [{ tool: "calculator", calls: 3, failed: 1 }],
};
const base = {
  usage: {},
  error: null,
  started_at: now,
  finished_at: now,
  tool_call_count: 0,
  inputs: null,
  output: null,
};
const RUNS = {
  total: 2,
  items: [
    {
      ...base,
      id: "r-1",
      kind: "agent",
      status: "completed",
      agent_id: "a-1",
      conversation_id: "c-1",
      workflow_id: null,
      agent_name: "Calc",
      workflow_name: null,
      usage: { total_tokens: 15 },
      tool_call_count: 1,
    },
    {
      ...base,
      id: "r-2",
      kind: "workflow",
      status: "failed",
      agent_id: null,
      conversation_id: null,
      workflow_id: "w-1",
      agent_name: null,
      workflow_name: "Flow",
      error: "Node write failed",
      inputs: { topic: "tides" },
    },
  ],
};

describe("Runs page", () => {
  it("shows real usage, history and a run's timeline, and re-runs workflows", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /analytics/summary?days=7": SUMMARY,
      "GET /runs?limit=25&offset=0": RUNS,
      "GET /runs?status=failed&limit=25&offset=0": {
        total: 1,
        items: [RUNS.items[1]],
      },
      "GET /runs/r-2/events": [
        {
          seq: 1,
          type: "node.started",
          payload: { node_id: "write", node_type: "llm", label: "Write" },
          created_at: now,
        },
        {
          seq: 2,
          type: "node.failed",
          payload: { node_id: "write", error: "model down" },
          created_at: now,
        },
      ],
      "POST /workflows/w-1/runs": { id: "r-3", status: "queued" },
    });
    renderApp("/runs");
    expect(
      await screen.findByLabelText("Success rate: 50%"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Avg / p95 duration: 1.5 s / 2.4 s"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Tokens (in / out): 40 / 20"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Top tools")).getByText("calculator"),
    ).toBeInTheDocument();

    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByLabelText("Filter by status"),
      "failed",
    );
    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Flow" }));
    const detail = screen.getByLabelText("Run details");
    expect(within(detail).getByText("Node write failed")).toBeInTheDocument();
    expect(
      await within(detail).findByText(/✗ write: model down/),
    ).toBeInTheDocument();
    await userEvent.click(
      within(detail).getByRole("button", { name: "Run again" }),
    );
    await waitFor(() =>
      expect(
        calls.find(
          (c) => c.method === "POST" && c.path === "/workflows/w-1/runs",
        )?.body,
      ).toEqual({ inputs: { topic: "tides" } }),
    );
  });

  it("says usage is unavailable instead of showing numbers when the API is down", async () => {
    mockApiDown();
    renderApp("/runs");
    expect(await screen.findByText(/Usage is unavailable/)).toBeInTheDocument();
    expect(await screen.findByText("Could not load runs")).toBeInTheDocument();
  });
});
