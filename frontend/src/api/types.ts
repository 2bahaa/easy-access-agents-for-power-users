/**
 * API types mirroring backend/app/schemas (docs/API_DESIGN.md). Keep in sync.
 */

/** The API returns every key (null = provider default); writes may omit them. */
export interface ModelParams {
  temperature?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
  /** Ollama only. */
  num_ctx?: number | null;
  /** Ollama only. */
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
  /** Workspace provider connection; null = the server's built-in provider. */
  connection_id?: string | null;
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
  connection_id?: string | null;
  provider: string;
  model: string;
  updated_at: string;
}

export interface Agent extends AgentSummary {
  /** Latest published version (null = never published); chats run it. */
  published_version?: number | null;
  /** True when the draft differs from the latest published version. */
  has_unpublished_changes?: boolean;
  model_params: ModelParams;
  system_prompt: string;
  skills: SkillRef[];
  tools: ToolSelection[];
  max_tool_calls: number;
  run_timeout_s: number;
  created_at: string;
}

export interface SkillWrite {
  category?: string;
  tags?: string[];
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
  category?: string;
  tags?: string[];
  version?: number;
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

export type ProviderKind = "ollama" | "openai" | "openai_compatible" | "anthropic" | "gemini";

/** A provider an agent can use: a server built-in (name "ollama") or a workspace connection. */
export interface ProviderInfo {
  /** Built-ins: registry name; connections: their id. Used in /providers/{name}/… URLs. */
  name: string;
  id: string | null;
  label: string;
  kind: ProviderKind;
  builtin: boolean;
  base_url: string | null;
  has_secret: boolean;
  secret_hint: string | null;
  available: boolean | null;
  status: "ok" | "error" | "unknown";
  last_error: string | null;
  last_checked_at: string | null;
}

export interface ProviderConnectionWrite {
  name?: string;
  kind?: ProviderKind;
  base_url?: string | null;
  /** Write-only. Omit to keep the stored key; "" removes it. */
  api_key?: string | null;
}

export interface ProbeResult {
  model: string;
  supports_tools: boolean;
  detail: string;
}

export interface ModelInfo {
  name: string;
  size: number | null;
  /** null = the provider does not say (use the tool-calling check or set it in Providers). */
  supports_tools: boolean | null;
  supports_thinking: boolean | null;
  tools_source?: "provider" | "probe" | "user" | null;
  context_window?: number | null;
  display_name?: string | null;
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

export interface ConversationSummary {
  id: string;
  agent_id: string;
  title: string;
  kind?: "chat" | "playground";
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  run_id: string | null;
  seq: number;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls: Array<{ id: string; name: string; args: Record<string, unknown> }> | null;
  tool_call_id: string | null;
  tool_name: string | null;
  created_at: string;
}

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "limit_exceeded" | "timeout";

export interface Run {
  id: string;
  conversation_id: string;
  agent_id: string;
  status: RunStatus;
  tool_call_count: number;
  usage: Record<string, number>;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface Conversation extends ConversationSummary {
  messages: Message[];
  runs: Run[];
}

export interface RunEventRecord {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

// ---- auth & organization ----

export type Role = "viewer" | "editor" | "admin" | "owner";

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
}

export interface Workspace {
  id: string;
  org_id: string;
  name: string;
  slug: string;
}

export interface OrgMembership {
  id: string;
  name: string;
  role: Role;
  workspaces: Workspace[];
}

export interface Me {
  user: { id: string; email: string; name: string };
  organizations: OrgMembership[];
  current_workspace_id: string;
  role: Role;
}

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  joined_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  role: Role;
  user_id: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  token: string;
}

export interface AuditEntry {
  id: number;
  workspace_id: string | null;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

// ---- agent platform (versions, templates, import/export) ----

export interface AgentVersionSummary {
  version: number;
  note: string;
  created_by: string | null;
  created_at: string;
}

export interface AgentVersion extends AgentVersionSummary {
  write_config: AgentWrite;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  system_prompt: string;
  tools: ToolSelection[];
  model_params: ModelParams;
  max_tool_calls: number;
  run_timeout_s: number;
  suggested_skills: string[];
}

/** Portable agent definition ("eaa.agent/v1"): no ids, secrets or conversations. */
export interface AgentExportDocument {
  format: "eaa.agent/v1";
  exported_at?: string | null;
  agent: Record<string, unknown>;
  skills: Array<Record<string, unknown>>;
}

export interface ImportResult {
  agent_id: string;
  created_skills: string[];
  reused_skills: string[];
}

export interface SkillVersion {
  version: number;
  name: string;
  description: string;
  content_md: string;
  created_by: string | null;
  created_at: string;
}
