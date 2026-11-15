import type { AgentEvent } from "../api/events";
import { readSSE } from "../api/sse";
import type {
  Approval,
  Conversation,
  ConversationSummary,
  RunEventRecord,
} from "../api/types";

export interface AgentClientOptions {
  /** API root, e.g. "https://agents.example.com/api". */
  baseUrl: string;
  /** Returns a bearer token: an `eaa_…` API key (server-side) or a user access token. */
  getToken?: () => string | null | Promise<string | null>;
  /** Selects a workspace other than the token's default. */
  workspaceId?: string;
  fetch?: typeof fetch;
}

export interface AgentClient {
  createConversation(agentId: string): Promise<ConversationSummary>;
  getConversation(id: string): Promise<Conversation>;
  /** Sends a message and yields the run's events as they stream. */
  sendMessage(
    conversationId: string,
    content: string,
    signal?: AbortSignal,
  ): AsyncGenerator<AgentEvent>;
  /** Follows a run (live or finished) from an event sequence number. */
  followRun(
    runId: string,
    after?: number,
    signal?: AbortSignal,
  ): AsyncGenerator<AgentEvent>;
  listRunEvents(runId: string): Promise<RunEventRecord[]>;
  cancelRun(runId: string): Promise<void>;
  listApprovals(status?: string): Promise<Approval[]>;
  /** Approve (optionally with corrected args, still schema-validated) or reject; returns the continuation run once all decisions are in. */
  decideApproval(
    id: string,
    decision: "approve" | "reject",
    options?: { args?: Record<string, unknown>; note?: string },
  ): Promise<{ approval: Approval; continuation_run_id: string | null }>;
  startWorkflowRun(
    workflowId: string,
    inputs: Record<string, string>,
  ): Promise<{ id: string }>;
}

/** A small fetch-based client for hosts that do not bring their own data layer. */
export function createAgentClient(options: AgentClientOptions): AgentClient {
  const base = options.baseUrl.replace(/\/$/, "");
  const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis);

  async function call(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = await options.getToken?.();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (options.workspaceId) headers.set("X-Workspace-Id", options.workspaceId);
    if (init.body) headers.set("Content-Type", "application/json");
    const response = await doFetch(`${base}${path}`, { ...init, headers });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = (await response.json()) as {
          detail?: string;
          title?: string;
        };
        detail = body.detail ?? body.title ?? detail;
      } catch {
        /* not JSON */
      }
      throw new Error(`${response.status}: ${detail}`);
    }
    return response;
  }
  const json = async <T>(path: string, init?: RequestInit): Promise<T> =>
    (await call(path, init)).json() as Promise<T>;

  async function* events(response: Response): AsyncGenerator<AgentEvent> {
    if (!response.body) throw new Error("The server returned an empty stream.");
    for await (const message of readSSE(response.body)) {
      if (message.data) yield JSON.parse(message.data) as AgentEvent;
    }
  }

  return {
    createConversation: (agentId) =>
      json("/conversations", {
        method: "POST",
        body: JSON.stringify({ agent_id: agentId }),
      }),
    getConversation: (id) => json(`/conversations/${id}`),
    async *sendMessage(conversationId, content, signal) {
      const response = await call(`/conversations/${conversationId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
        headers: { Accept: "text/event-stream" },
        signal,
      });
      yield* events(response);
    },
    async *followRun(runId, after = 0, signal) {
      yield* events(
        await call(`/runs/${runId}/stream?after=${after}`, {
          headers: { Accept: "text/event-stream" },
          signal,
        }),
      );
    },
    listRunEvents: (runId) => json(`/runs/${runId}/events`),
    cancelRun: async (runId) => {
      await call(`/runs/${runId}/cancel`, { method: "POST" });
    },
    listApprovals: (status = "pending") =>
      json(`/approvals?status=${encodeURIComponent(status)}`),
    decideApproval: (id, decision, opts = {}) =>
      json(`/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          args: opts.args ?? null,
          note: opts.note ?? "",
        }),
      }),
    startWorkflowRun: (workflowId, inputs) =>
      json(`/workflows/${workflowId}/runs`, {
        method: "POST",
        body: JSON.stringify({ inputs }),
      }),
  };
}
