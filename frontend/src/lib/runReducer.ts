import type { AgentEvent, RunFailureCode, ToolFailureKind } from "../api/events";
import type { RunEventRecord } from "../api/types";

/** Timeline entries derived from a run's events (live or persisted). */
export type TimelineItem =
  | { kind: "started"; seq: number; model: string; ts: string }
  | { kind: "reasoning"; seq: number; text: string }
  | {
      kind: "tool";
      seq: number;
      callId: string;
      tool: string;
      args: Record<string, unknown>;
      status: "running" | "completed" | "failed";
      result?: string;
      error?: string;
      errorKind?: ToolFailureKind;
      durationMs?: number;
    }
  | { kind: "message"; seq: number; messageId: string; content: string }
  | {
      kind: "end";
      seq: number;
      status: "completed" | "failed" | "cancelled";
      code?: RunFailureCode | "connection";
      message?: string;
      usage?: Record<string, number>;
      durationMs?: number;
      toolCallCount?: number;
    };

export type ToolItem = Extract<TimelineItem, { kind: "tool" }>;

export interface RunState {
  runId: string | null;
  status: "idle" | "streaming" | "completed" | "failed" | "cancelled";
  /** Assistant text streamed since the last completed message. */
  draft: string;
  items: TimelineItem[];
  error: string | null;
}

export const initialRunState: RunState = {
  runId: null,
  status: "idle",
  draft: "",
  items: [],
  error: null,
};

export type RunAction =
  | AgentEvent
  | { type: "local.start" }
  | { type: "local.error"; message: string }
  /** The client stopped the run before the server confirmed it (e.g. aborted fetch). */
  | { type: "local.aborted" }
  | { type: "local.reset" };

const FAILURE_TEXT: Partial<Record<RunFailureCode, string>> = {
  limit_exceeded: "Stopped: the tool call limit was reached.",
  timeout: "Stopped: the run timed out.",
};

export function failureText(code: string | undefined, message: string | undefined): string {
  return (code && FAILURE_TEXT[code as RunFailureCode]) || message || "The run failed.";
}

function updateTool(items: TimelineItem[], callId: string, patch: Partial<ToolItem>): TimelineItem[] {
  return items.map((item) =>
    item.kind === "tool" && item.callId === callId ? { ...item, ...patch } : item,
  );
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "local.reset":
      return initialRunState;
    case "local.start":
      return { ...initialRunState, status: "streaming" };
    case "local.error": {
      if (state.status !== "streaming" && state.status !== "idle") return state;
      const seq = (state.items.at(-1)?.seq ?? 0) + 1;
      return {
        ...state,
        status: "failed",
        error: action.message,
        draft: "",
        items: [...state.items, { kind: "end", seq, status: "failed", code: "connection", message: action.message }],
      };
    }
    case "local.aborted": {
      if (state.status !== "streaming") return state;
      const seq = (state.items.at(-1)?.seq ?? 0) + 1;
      return { ...state, status: "cancelled", draft: "", items: [...state.items, { kind: "end", seq, status: "cancelled" }] };
    }
    case "run.started":
      return {
        ...state,
        runId: action.run_id,
        status: "streaming",
        items: [...state.items, { kind: "started", seq: action.seq, model: action.model, ts: action.ts }],
      };
    case "reasoning.delta": {
      const last = state.items.at(-1);
      if (last?.kind === "reasoning") {
        return { ...state, items: [...state.items.slice(0, -1), { ...last, text: last.text + action.text }] };
      }
      return { ...state, items: [...state.items, { kind: "reasoning", seq: action.seq, text: action.text }] };
    }
    case "message.delta":
      return { ...state, draft: state.draft + action.text };
    case "message.completed":
      return {
        ...state,
        draft: "",
        items: [
          ...state.items,
          { kind: "message", seq: action.seq, messageId: action.message_id, content: action.content },
        ],
      };
    case "tool.call.started":
      return {
        ...state,
        // Text streamed before a tool call is part of that turn; keep only completed messages.
        draft: "",
        items: [
          ...state.items,
          {
            kind: "tool",
            seq: action.seq,
            callId: action.call_id,
            tool: action.tool,
            args: action.args,
            status: "running",
          },
        ],
      };
    case "tool.call.completed":
      return {
        ...state,
        items: updateTool(state.items, action.call_id, {
          status: "completed",
          result: action.result,
          durationMs: action.duration_ms,
        }),
      };
    case "tool.call.failed":
      return {
        ...state,
        items: updateTool(state.items, action.call_id, {
          status: "failed",
          error: action.error,
          errorKind: action.kind,
        }),
      };
    case "run.completed":
      return {
        ...state,
        status: "completed",
        draft: "",
        items: [
          ...state.items,
          {
            kind: "end",
            seq: action.seq,
            status: "completed",
            usage: action.usage,
            durationMs: action.duration_ms,
            toolCallCount: action.tool_call_count,
          },
        ],
      };
    case "run.failed":
      return {
        ...state,
        status: "failed",
        draft: "",
        error: failureText(action.code, action.message),
        items: [
          ...state.items,
          { kind: "end", seq: action.seq, status: "failed", code: action.code, message: action.message },
        ],
      };
    case "run.cancelled":
      return {
        ...state,
        status: "cancelled",
        draft: "",
        items: [...state.items, { kind: "end", seq: action.seq, status: "cancelled" }],
      };
    default:
      return state;
  }
}

/** Rebuild run state from persisted `run_events` rows (no token deltas are stored). */
export function replayRunEvents(runId: string, records: RunEventRecord[]): RunState {
  return records.reduce<RunState>(
    (state, record) =>
      runReducer(state, {
        ...record.payload,
        type: record.type,
        seq: record.seq,
        run_id: runId,
        ts: record.created_at,
      } as AgentEvent),
    initialRunState,
  );
}
