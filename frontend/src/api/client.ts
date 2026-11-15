import type { AgentEvent } from "./events";
import { API_BASE_URL, authFetch } from "./session";
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
  ProbeResult,
  ProviderConnectionWrite,
  AgentExportDocument,
  AgentTemplate,
  AgentVersion,
  AgentVersionSummary,
  ImportResult,
  SkillVersion,
  ApiKey,
  ApiKeyCreated,
  AuditEntry,
  Me,
  Member,
  Role,
  TokenResponse,
  Workspace,
} from "./types";

export { API_BASE_URL };

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
  const response = await authFetch(`${API_BASE_URL}${path}`, {
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
 * signal only stops following — the run keeps executing (use `api.cancelRun`).
 */
export async function* streamMessage(
  conversationId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await authFetch(`${API_BASE_URL}/conversations/${conversationId}/messages`, {
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

/**
 * Follow a run (active or finished) from any page load: replays persisted events after
 * `after`, then streams live events until the run ends. Runs are durable: aborting only
 * stops following, the run keeps executing on the server.
 */
export async function* followRun(runId: string, signal?: AbortSignal, after = 0): AsyncGenerator<AgentEvent> {
  const response = await authFetch(`${API_BASE_URL}/runs/${runId}/stream?after=${after}`, {
    headers: { Accept: "text/event-stream" },
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
  createConversation: (agentId: string, playground = false) =>
    request<ConversationSummary>("/conversations", json("POST", { agent_id: agentId, playground })),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),

  getRun: (id: string) => request<Run>(`/runs/${id}`),
  listRunEvents: (id: string) => request<RunEventRecord[]>(`/runs/${id}/events`),
  cancelRun: (id: string) => request<void>(`/runs/${id}/cancel`, { method: "POST" }),
  listProviders: () => request<ProviderInfo[]>("/providers"),

  // ---- agent platform ----
  listAgentTemplates: () => request<AgentTemplate[]>("/agent-templates"),
  duplicateAgent: (id: string, name?: string) =>
    request<Agent>(`/agents/${id}/duplicate`, json("POST", name ? { name } : {})),
  exportAgent: (id: string) => request<AgentExportDocument>(`/agents/${id}/export`),
  importAgent: (doc: AgentExportDocument) => request<ImportResult>("/agents/import", json("POST", doc)),
  publishAgent: (id: string, note: string) =>
    request<AgentVersionSummary>(`/agents/${id}/publish`, json("POST", { note })),
  listAgentVersions: (id: string) => request<AgentVersionSummary[]>(`/agents/${id}/versions`),
  getAgentVersion: (id: string, version: number) => request<AgentVersion>(`/agents/${id}/versions/${version}`),
  restoreAgentVersion: (id: string, version: number) =>
    request<Agent>(`/agents/${id}/versions/${version}/restore`, { method: "POST" }),
  listSkillTemplates: () => request<SkillWrite[]>("/skill-templates"),
  listSkillVersions: (id: string) => request<SkillVersion[]>(`/skills/${id}/versions`),
  restoreSkillVersion: (id: string, version: number) =>
    request<Skill>(`/skills/${id}/versions/${version}/restore`, { method: "POST" }),
  exportSkill: async (id: string): Promise<string> => {
    const response = await authFetch(`${API_BASE_URL}/skills/${id}/export`, { headers: { Accept: "text/plain" } });
    if (!response.ok) throw await toApiError(response);
    return response.text();
  },
  importSkill: (markdown: string) => request<Skill>("/skills/import", json("POST", { markdown })),

  // ---- auth & organization ----
  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", json("POST", { email, password })),
  register: (email: string, password: string, name: string) =>
    request<TokenResponse>("/auth/register", json("POST", { email, password, name })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<Me>("/auth/me"),
  listWorkspaces: () => request<Workspace[]>("/workspaces"),
  createWorkspace: (name: string) => request<Workspace>("/workspaces", json("POST", { name })),
  listMembers: () => request<Member[]>("/members"),
  addMember: (email: string, role: Role) => request<Member>("/members", json("POST", { email, role })),
  updateMember: (userId: string, role: Role) =>
    request<void>(`/members/${userId}`, json("PATCH", { role })),
  removeMember: (userId: string) => request<void>(`/members/${userId}`, { method: "DELETE" }),
  listApiKeys: () => request<ApiKey[]>("/api-keys"),
  createApiKey: (name: string, role: Exclude<Role, "owner">, expiresInDays: number | null) =>
    request<ApiKeyCreated>("/api-keys", json("POST", { name, role, expires_in_days: expiresInDays })),
  revokeApiKey: (id: string) => request<void>(`/api-keys/${id}`, { method: "DELETE" }),
  listAudit: (before?: number) => request<AuditEntry[]>(`/audit?limit=100${before ? `&before=${before}` : ""}`),
  listModels: (provider: string) =>
    request<ModelInfo[]>(`/providers/${encodeURIComponent(provider)}/models`),
  createProvider: (data: ProviderConnectionWrite) => request<ProviderInfo>("/providers", json("POST", data)),
  updateProvider: (id: string, data: ProviderConnectionWrite) =>
    request<ProviderInfo>(`/providers/${id}`, json("PATCH", data)),
  deleteProvider: (id: string) => request<void>(`/providers/${id}`, { method: "DELETE" }),
  testProvider: (name: string) => request<ProviderInfo>(`/providers/${encodeURIComponent(name)}/test`, { method: "POST" }),
  setModelTools: (provider: string, model: string, supportsTools: boolean | null) =>
    request<void>(
      `/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}/capabilities`,
      json("PUT", { supports_tools: supportsTools }),
    ),
  probeModel: (provider: string, model: string) =>
    request<ProbeResult>(
      `/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}/probe`,
      { method: "POST" },
    ),
};
