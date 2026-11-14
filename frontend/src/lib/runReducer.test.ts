import type { AgentEvent } from "../api/events";
import { CALCULATOR_RUN, events } from "../test/stream";
import { initialRunState, replayRunEvents, runReducer, type RunState } from "./runReducer";

const reduce = (list: AgentEvent[], from: RunState = initialRunState) => list.reduce(runReducer, from);

describe("runReducer", () => {
  it("accumulates a streamed calculator run", () => {
    const midway = reduce(CALCULATOR_RUN.slice(0, 5), runReducer(initialRunState, { type: "local.start" }));
    expect(midway.status).toBe("streaming");
    expect(midway.runId).toBe("r-1");
    expect(midway.draft).toBe("The answer is **406.5**.");
    const tool = midway.items.find((i) => i.kind === "tool");
    expect(tool).toMatchObject({ status: "completed", result: "406.5", durationMs: 3, args: { expression: "17.5 * 23 + 4" } });

    const done = reduce(CALCULATOR_RUN.slice(5), midway);
    expect(done.status).toBe("completed");
    expect(done.draft).toBe("");
    expect(done.items.map((i) => i.kind)).toEqual(["started", "tool", "message", "end"]);
    expect(done.items.at(-1)).toMatchObject({ status: "completed", toolCallCount: 1, usage: { total_tokens: 42 } });
  });

  it("marks failed tool calls and runs", () => {
    const state = reduce(
      events("r-2", [
        { type: "run.started", agent_id: "a", model: "m", conversation_id: null, user_message_id: null },
        { type: "tool.call.started", call_id: "x", tool: "file_reader", args: { path: "../secret" } },
        { type: "tool.call.failed", call_id: "x", tool: "file_reader", error: "Path must be relative", kind: "validation" },
        { type: "run.failed", code: "limit_exceeded", message: "Tool call limit reached (1)" },
      ]),
    );
    expect(state.items[1]).toMatchObject({ status: "failed", errorKind: "validation", error: "Path must be relative" });
    expect(state.status).toBe("failed");
    expect(state.error).toBe("Stopped: the tool call limit was reached.");
  });

  it("merges consecutive reasoning deltas", () => {
    const state = reduce(
      events("r", [
        { type: "reasoning.delta", text: "Let me " },
        { type: "reasoning.delta", text: "think." },
        { type: "message.delta", text: "Hi" },
      ]),
    );
    expect(state.items).toEqual([{ kind: "reasoning", seq: 1, text: "Let me think." }]);
  });

  it("handles cancellation and local errors", () => {
    const started = runReducer(initialRunState, { type: "local.start" });
    expect(runReducer(started, { type: "local.aborted" }).status).toBe("cancelled");
    const errored = runReducer(started, { type: "local.error", message: "Cannot reach the backend." });
    expect(errored).toMatchObject({ status: "failed", error: "Cannot reach the backend." });
    // A late local error never overrides a finished run.
    const finished = reduce(CALCULATOR_RUN);
    expect(runReducer(finished, { type: "local.error", message: "x" })).toBe(finished);
  });

  it("replays persisted run events into the same timeline (without deltas)", () => {
    const persisted = CALCULATOR_RUN.filter((e) => e.type !== "message.delta").map((e) => {
      const { type, seq, run_id: _r, ts, ...payload } = e as AgentEvent & Record<string, unknown>;
      return { type, seq, payload, created_at: ts };
    });
    const replayed = replayRunEvents("r-1", persisted);
    const live = reduce(CALCULATOR_RUN);
    expect(replayed.items.map((i) => i.kind)).toEqual(live.items.map((i) => i.kind));
    expect(replayed.status).toBe("completed");
  });
});
