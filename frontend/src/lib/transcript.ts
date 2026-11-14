import type { Message, Run } from "../api/types";
import { failureText, type RunState } from "./runReducer";

/** One row in the chat transcript. */
export type ChatItem =
  | { kind: "user"; id: string; content: string; runId: string | null }
  | { kind: "assistant"; id: string; content: string; runId: string | null }
  | {
      kind: "tool";
      id: string;
      tool: string;
      args: Record<string, unknown>;
      status: "running" | "completed" | "failed";
      result?: string;
      runId: string | null;
    }
  | { kind: "notice"; id: string; tone: "info" | "warning" | "error"; text: string; runId: string | null };

const ERROR_PREFIX = "Error:";

function runNotice(run: Run): ChatItem | null {
  const base = { id: `notice-${run.id}`, runId: run.id } as const;
  switch (run.status) {
    case "cancelled":
      return { ...base, kind: "notice", tone: "info", text: "Run cancelled." };
    case "limit_exceeded":
      return { ...base, kind: "notice", tone: "warning", text: failureText("limit_exceeded", undefined) };
    case "timeout":
      return { ...base, kind: "notice", tone: "warning", text: failureText("timeout", undefined) };
    case "failed":
      return { ...base, kind: "notice", tone: "error", text: run.error ?? "The run failed." };
    default:
      return null;
  }
}

/** Build the transcript from persisted messages and runs. */
export function buildTranscript(messages: Message[], runs: Run[]): ChatItem[] {
  const results = new Map(
    messages.filter((m) => m.role === "tool" && m.tool_call_id).map((m) => [m.tool_call_id!, m]),
  );
  const items: ChatItem[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      items.push({ kind: "user", id: m.id, content: m.content, runId: m.run_id });
    } else if (m.role === "assistant") {
      for (const call of m.tool_calls ?? []) {
        const result = results.get(call.id);
        const failed = !result || result.content.startsWith(ERROR_PREFIX);
        items.push({
          kind: "tool",
          id: call.id,
          tool: call.name,
          args: call.args,
          status: failed ? "failed" : "completed",
          result: result?.content,
          runId: m.run_id,
        });
      }
      if (m.content.trim()) {
        items.push({ kind: "assistant", id: m.id, content: m.content, runId: m.run_id });
      }
    }
  }

  // Insert a notice after the last item of every run that did not complete normally.
  for (const run of runs) {
    const notice = runNotice(run);
    if (!notice) continue;
    let index = -1;
    items.forEach((item, i) => {
      if (item.runId === run.id) index = i;
    });
    items.splice(index + 1 || items.length, 0, notice);
  }
  return items;
}

/** Transcript rows for an in-flight run: the pending user message plus completed steps. */
export function liveTranscript(state: RunState, pendingContent: string | null): ChatItem[] {
  const runId = state.runId;
  const items: ChatItem[] = [];
  if (pendingContent !== null) {
    items.push({ kind: "user", id: "pending-user", content: pendingContent, runId });
  }
  for (const item of state.items) {
    if (item.kind === "tool") {
      items.push({
        kind: "tool",
        id: item.callId,
        tool: item.tool,
        args: item.args,
        status: item.status,
        result: item.result ?? item.error,
        runId,
      });
    } else if (item.kind === "message") {
      items.push({ kind: "assistant", id: item.messageId, content: item.content, runId });
    } else if (item.kind === "end" && item.status !== "completed") {
      items.push({
        kind: "notice",
        id: `live-end-${item.seq}`,
        tone: item.status === "cancelled" ? "info" : item.code === "limit_exceeded" || item.code === "timeout" ? "warning" : "error",
        text: item.status === "cancelled" ? "Run cancelled." : failureText(item.code, item.message),
        runId,
      });
    }
  }
  return items;
}
