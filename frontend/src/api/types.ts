/**
 * API types mirroring backend/app/schemas (docs/API_DESIGN.md). Keep in sync.
 */

export interface ModelParams {
  temperature?: number | null;
  num_ctx?: number | null;
  think?: boolean | null;
}

export interface ToolSelection {
  name: string;
  config: Record<string, unknown>;
}

export interface AgentWrite {
  name: string;
  description: string;
  provider: string;
  model: string;
  model_params: ModelParams;
  system_prompt: string;
  skill_ids: string[];
  tools: ToolSelection[];
  max_tool_calls: number;
  run_timeout_s: number;
}

export interface SkillRef {
  id: string;
  slug: string;
  name: string;
}

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  provider: string;
  model: string;
  updated_at: string;
}

export interface Agent extends AgentSummary {
  model_params: ModelParams;
  system_prompt: string;
  skills: SkillRef[];
  tools: ToolSelection[];
  max_tool_calls: number;
  run_timeout_s: number;
  created_at: string;
}

export interface SkillWrite {
  slug: string;
  name: string;
  description: string;
  content_md: string;
}

export interface SkillSummary {
  id: string;
  slug: string;
  name: string;
  description: string;
  is_builtin: boolean;
  updated_at: string;
}

export interface Skill extends SkillSummary {
  content_md: string;
  created_at: string;
}

/** The subset of JSON Schema produced by Pydantic that the UI understands. */
export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  examples?: unknown[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
}

export interface ToolInfo {
  name: string;
  description: string;
  args_schema: JsonSchema;
  config_schema: JsonSchema;
  timeout_s: number;
}

export interface ProviderInfo {
  name: string;
  available: boolean;
}

export interface ModelInfo {
  name: string;
  size: number | null;
  supports_tools: boolean;
  supports_thinking: boolean;
}

export interface Health {
  status: "ok" | "degraded";
  database: "ok" | "error";
  ollama: "ok" | "error";
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  errors?: Array<{ loc: Array<string | number>; msg: string; type: string }>;
}
