/**
 * Streaming event protocol — mirrors backend/app/runtime/events.py (docs/API_DESIGN.md §4).
 * Change both together.
 */

interface EventBase {
  run_id: string;
  seq: number;
  ts: string;
}

export interface RunStarted extends EventBase {
  type: "run.started";
  agent_id: string;
  model: string;
  conversation_id: string | null;
  user_message_id: string | null;
}

export interface ReasoningDelta extends EventBase {
  type: "reasoning.delta";
  text: string;
}

export interface MessageDelta extends EventBase {
  type: "message.delta";
  text: string;
}

export interface MessageCompleted extends EventBase {
  type: "message.completed";
  message_id: string;
  content: string;
}

export interface ToolCallStarted extends EventBase {
  type: "tool.call.started";
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface ToolCallCompleted extends EventBase {
  type: "tool.call.completed";
  call_id: string;
  tool: string;
  result: string;
  duration_ms: number;
}

export type ToolFailureKind = "validation" | "permission" | "timeout" | "execution";

export interface ToolCallFailed extends EventBase {
  type: "tool.call.failed";
  call_id: string;
  tool: string;
  error: string;
  kind: ToolFailureKind;
}

export interface RunCompleted extends EventBase {
  type: "run.completed";
  status: "completed";
  tool_call_count: number;
  usage: Record<string, number>;
  duration_ms: number;
}

export type RunFailureCode =
  | "limit_exceeded"
  | "timeout"
  | "provider_error"
  | "model_no_tool_support"
  | "internal_error";

export interface RunFailed extends EventBase {
  type: "run.failed";
  code: RunFailureCode;
  message: string;
}

export interface RunCancelled extends EventBase {
  type: "run.cancelled";
}

/** A tool call was held for human approval (not executed). */
export interface ApprovalRequested extends EventBase {
  type: "approval.requested";
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
}

/** Terminal: the run paused until humans decide; a continuation run follows. */
export interface RunWaitingApproval extends EventBase {
  type: "run.waiting_approval";
  pending: string[];
}

export type AgentEvent =
  | RunStarted
  | ReasoningDelta
  | MessageDelta
  | MessageCompleted
  | ToolCallStarted
  | ToolCallCompleted
  | ToolCallFailed
  | ApprovalRequested
  | RunCompleted
  | RunFailed
  | RunCancelled
  | RunWaitingApproval;

export const TERMINAL_EVENTS = new Set<AgentEvent["type"]>([
  "run.completed",
  "run.failed",
  "run.cancelled",
  "run.waiting_approval",
]);
