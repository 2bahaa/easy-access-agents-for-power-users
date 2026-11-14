import type { Message, Run } from "../api/types";
import { CALCULATOR_RUN } from "../test/stream";
import { initialRunState, runReducer } from "./runReducer";
import { buildTranscript, liveTranscript } from "./transcript";

const msg = (m: Partial<Message> & Pick<Message, "id" | "seq" | "role">): Message => ({
  run_id: "r-1",
  content: "",
  tool_calls: null,
  tool_call_id: null,
  tool_name: null,
  created_at: "2026-11-14T10:00:00Z",
  ...m,
});

const run = (id: string, status: Run["status"], error: string | null = null): Run => ({
  id,
  conversation_id: "c-1",
  agent_id: "a-1",
  status,
  tool_call_count: 0,
  usage: {},
  error,
  started_at: "2026-11-14T10:00:00Z",
  finished_at: null,
});

describe("buildTranscript", () => {
  it("pairs tool calls with their results and hides empty assistant turns", () => {
    const items = buildTranscript(
      [
        msg({ id: "u", seq: 1, role: "user", content: "What is 2+2?" }),
        msg({ id: "a1", seq: 2, role: "assistant", tool_calls: [{ id: "c1", name: "calculator", args: { expression: "2+2" } }] }),
        msg({ id: "t1", seq: 3, role: "tool", content: "4", tool_call_id: "c1", tool_name: "calculator" }),
        msg({ id: "a2", seq: 4, role: "assistant", content: "It is 4." }),
      ],
      [run("r-1", "completed")],
    );
    expect(items.map((i) => i.kind)).toEqual(["user", "tool", "assistant"]);
    expect(items[1]).toMatchObject({ tool: "calculator", status: "completed", result: "4" });
  });

  it("marks error results as failed tool calls", () => {
    const items = buildTranscript(
      [
        msg({ id: "a1", seq: 1, role: "assistant", tool_calls: [{ id: "c1", name: "file_reader", args: { path: "x" } }] }),
        msg({ id: "t1", seq: 2, role: "tool", content: "Error: File not found: x", tool_call_id: "c1" }),
      ],
      [],
    );
    expect(items[0]).toMatchObject({ status: "failed" });
  });

  it("adds a notice after runs that did not complete", () => {
    const items = buildTranscript(
      [
        msg({ id: "u1", seq: 1, role: "user", content: "hi", run_id: "r-1" }),
        msg({ id: "u2", seq: 2, role: "user", content: "again", run_id: "r-2" }),
        msg({ id: "a2", seq: 3, role: "assistant", content: "partial", run_id: "r-2" }),
      ],
      [run("r-1", "failed", "Model provider error: connection refused"), run("r-2", "cancelled")],
    );
    expect(items.map((i) => (i.kind === "notice" ? `notice:${i.tone}` : i.kind))).toEqual([
      "user",
      "notice:error",
      "user",
      "assistant",
      "notice:info",
    ]);
    expect(items[1]).toMatchObject({ text: "Model provider error: connection refused" });
  });
});

describe("liveTranscript", () => {
  it("shows the pending user message and completed steps of the live run", () => {
    const state = CALCULATOR_RUN.slice(0, 6).reduce(runReducer, initialRunState);
    const items = liveTranscript(state, "What is 17.5 * 23 + 4?");
    expect(items.map((i) => i.kind)).toEqual(["user", "tool", "assistant"]);
    expect(items.every((i) => i.runId === "r-1")).toBe(true);
  });

  it("shows why a live run stopped", () => {
    const state = runReducer(runReducer(initialRunState, { type: "local.start" }), {
      type: "local.error",
      message: "Cannot reach the backend.",
    });
    expect(liveTranscript(state, "hi").at(-1)).toMatchObject({ kind: "notice", tone: "error", text: "Cannot reach the backend." });
  });
});
