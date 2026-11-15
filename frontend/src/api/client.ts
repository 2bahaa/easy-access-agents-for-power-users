import type { AgentEvent } from "./events";
import { readSSE } from "./sse";
import type {
  Agent,
  AgentSummary,
  AgentWrite,
  Conversation,
  ConversationSummary,
  Health,
  ModelInfo,
  ProblemDetails,
  ProviderInfo,
  Run,
  RunEventRecord,
  Skill,
  SkillSummary,
  SkillWrite,
  ToolInfo,
} from "./types";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api";

/** Error carrying the backend's problem-JSON body. */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly problem: ProblemDetails;

  constructor(status: number, problem: ProblemDetails) {
    const detail = problem.detail ?? problem.title ?? `Request failed (${status})`;
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.title = problem.title ?? "Request failed";
    this.detail = detail;
    this.problem = problem;
  }

  /** Field-level validation messages keyed by the last path segment (e.g. "name"). */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const err of this.problem.errors ?? []) {
      const key = String(err.loc[err.loc.length - 1] ?? "");
      if (key && !out[key]) out[key] = err.msg;
    }
    return out;
  }
}

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const fields = error.fieldErrors();
    const first = Object.entries(fields)[0];
    return first && error.status === 422 && error.detail === "Request validation failed"
      ? `${first[0]}: ${first[1]}`
      : error.detail;
  }
  if (error instanceof TypeError) return "Cannot reach the backend. Is the API running?";
  return error instanceof Error ? error.message : String(error);
}

async function toApiError(response: Response): Promise<ApiError> {
  let problem: ProblemDetails;
  try {
    problem = (await response.json()) as ProblemDetails;
  } catch {
    problem = { detail: response.statusText || `Request failed (${response.status})` };
  }
  return new ApiError(response.status, problem);
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Send a chat message and stream the run's events (SSE over a POST response).
 * Errors before the stream starts (404/409/422) are thrown as ApiError; aborting the
 * signal closes the connection, which cancels the run on the server.
 */
export async function* streamMessage(
  conversationId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch(`${API_BASE_URL}/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new Error("The server returned an empty stream.");
  for await (const message of readSSE(response.body)) {
    if (!message.data) continue;
    yield JSON.parse(message.data) as AgentEvent;
  }
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/health"),

  listAgents: () => request<AgentSummary[]>("/agents"),
  getAgent: (id: string) => request<Agent>(`/agents/${id}`),
  createAgent: (data: AgentWrite) => request<Agent>("/agents", json("POST", data)),
  updateAgent: (id: string, data: AgentWrite) => request<Agent>(`/agents/${id}`, json("PUT", data)),
  deleteAgent: (id: string) => request<void>(`/agents/${id}`, { method: "DELETE" }),

  listSkills: () => request<SkillSummary[]>("/skills"),
  getSkill: (id: string) => request<Skill>(`/skills/${id}`),
  createSkill: (data: SkillWrite) => request<Skill>("/skills", json("POST", data)),
  updateSkill: (id: string, data: SkillWrite) => request<Skill>(`/skills/${id}`, json("PUT", data)),
  deleteSkill: (id: string) => request<void>(`/skills/${id}`, { method: "DELETE" }),

  listTools: () => request<ToolInfo[]>("/tools"),

  listAllConversations: () => request<ConversationSummary[]>("/conversations"),
  listConversations: (agentId: string) =>
    request<ConversationSummary[]>(`/conversations?agent_id=${encodeURIComponent(agentId)}`),
  getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),
  createConversation: (agentId: string) =>
    request<ConversationSummary>("/conversations", json("POST", { agent_id: agentId })),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),

  getRun: (id: string) => request<Run>(`/runs/${id}`),
  listRunEvents: (id: string) => request<RunEventRecord[]>(`/runs/${id}/events`),
  cancelRun: (id: string) => request<void>(`/runs/${id}/cancel`, { method: "POST" }),
  listProviders: () => request<ProviderInfo[]>("/providers"),
  listModels: (provider: string) =>
    request<ModelInfo[]>(`/providers/${encodeURIComponent(provider)}/models`),
};
