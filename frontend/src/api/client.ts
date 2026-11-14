import type {
  Agent,
  AgentSummary,
  AgentWrite,
  Health,
  ModelInfo,
  ProblemDetails,
  ProviderInfo,
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

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let problem: ProblemDetails;
    try {
      problem = (await response.json()) as ProblemDetails;
    } catch {
      problem = { detail: response.statusText || `Request failed (${response.status})` };
    }
    throw new ApiError(response.status, problem);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
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
  listProviders: () => request<ProviderInfo[]>("/providers"),
  listModels: (provider: string) =>
    request<ModelInfo[]>(`/providers/${encodeURIComponent(provider)}/models`),
};
