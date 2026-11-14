import type { AgentEvent } from "../api/events";

type Payload = { type: AgentEvent["type"] } & Record<string, unknown>;

/** Build protocol-shaped events with run_id/seq/ts filled in. */
export function events(runId: string, payloads: Payload[]): AgentEvent[] {
  return payloads.map(
    (p, i) => ({ run_id: runId, seq: i + 1, ts: "2026-11-14T10:00:00Z", ...p }) as unknown as AgentEvent,
  );
}

export function toSSE(list: AgentEvent[]): string {
  return list
    .map((e) => `id: ${e.seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`)
    .join(": ping\n\n");
}

/** A streaming Response that emits the SSE text in small chunks, optionally pausing. */
export function sseResponse(text: string, options: { chunkSize?: number; holdOpen?: Promise<void> } = {}) {
  const encoder = new TextEncoder();
  const size = options.chunkSize ?? 17;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (let i = 0; i < text.length; i += size) {
        controller.enqueue(encoder.encode(text.slice(i, i + size)));
        await Promise.resolve();
      }
      if (options.holdOpen) await options.holdOpen;
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

/** The canonical calculator run used across tests. */
export const CALCULATOR_RUN = events("r-1", [
  { type: "run.started", agent_id: "a-1", model: "qwen3:4b", conversation_id: "c-1", user_message_id: "m-1" },
  { type: "tool.call.started", call_id: "call-1", tool: "calculator", args: { expression: "17.5 * 23 + 4" } },
  { type: "tool.call.completed", call_id: "call-1", tool: "calculator", result: "406.5", duration_ms: 3 },
  { type: "message.delta", text: "The answer " },
  { type: "message.delta", text: "is **406.5**." },
  { type: "message.completed", message_id: "m-3", content: "The answer is **406.5**." },
  { type: "run.completed", status: "completed", tool_call_count: 1, usage: { total_tokens: 42 }, duration_ms: 1500 },
]);
