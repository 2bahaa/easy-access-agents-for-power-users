import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { initialRunState, runReducer } from "../lib/runReducer";
import { CALCULATOR_RUN, events } from "../test/stream";
import { AgentRunTimeline } from "./AgentRunTimeline";

describe("AgentRunTimeline", () => {
  it("shows each step of a completed run", () => {
    const state = CALCULATOR_RUN.reduce(runReducer, initialRunState);
    render(<AgentRunTimeline items={state.items} status={state.status} />);
    expect(screen.getByText("Run started")).toBeInTheDocument();
    expect(screen.getByText("qwen3:4b")).toBeInTheDocument();
    expect(screen.getByText("Calculator")).toBeInTheDocument();
    expect(screen.getByText("3 ms")).toBeInTheDocument();
    expect(screen.getByText(/"expression": "17.5 \* 23 \+ 4"/)).toBeInTheDocument();
    expect(screen.getByText("406.5")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("42 tokens")).toBeInTheDocument();
    expect(screen.getByText("1 tool call")).toBeInTheDocument();
  });

  it("shows a running tool and a live indicator while streaming", () => {
    const state = CALCULATOR_RUN.slice(0, 2).reduce(runReducer, initialRunState);
    render(<AgentRunTimeline items={state.items} status="streaming" />);
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("Working…")).toBeInTheDocument();
  });

  it("explains failures", () => {
    const state = events("r", [
      { type: "run.started", agent_id: "a", model: "m", conversation_id: null, user_message_id: null },
      { type: "tool.call.started", call_id: "x", tool: "file_reader", args: { path: "../x" } },
      { type: "tool.call.failed", call_id: "x", tool: "file_reader", error: "Path must be relative", kind: "validation" },
      { type: "run.failed", code: "model_no_tool_support", message: "Model 'gemma' does not support tool calling." },
    ]).reduce(runReducer, initialRunState);
    render(<AgentRunTimeline items={state.items} status={state.status} />);
    expect(screen.getByText("validation")).toBeInTheDocument();
    expect(screen.getByText("Path must be relative")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/does not support tool calling/)).toBeInTheDocument();
  });

  it("collapses reasoning by default", async () => {
    const state = events("r", [{ type: "reasoning.delta", text: "Thinking hard" }]).reduce(runReducer, initialRunState);
    render(<AgentRunTimeline items={state.items} status="completed" />);
    expect(screen.queryByText("Thinking hard")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reasoning" }));
    expect(screen.getByText("Thinking hard")).toBeInTheDocument();
  });

  it("has helpful empty states", () => {
    const { rerender } = render(<AgentRunTimeline items={[]} status="idle" emptyText="Nothing yet." />);
    expect(screen.getByText("Nothing yet.")).toBeInTheDocument();
    rerender(<AgentRunTimeline items={[]} status="streaming" />);
    expect(screen.getByText("Waiting for the first event…")).toBeInTheDocument();
  });
});
