import type { Agent, AgentWrite, ToolSelection } from "../api/types";

/** Editable agent state used by AgentBuilder (UI-friendly shape of AgentWrite). */
export interface AgentFormValues {
  name: string;
  description: string;
  provider: string;
  /** Workspace provider connection; null = built-in provider named `provider`. */
  connectionId: string | null;
  model: string;
  temperature: number | null; // null = model default
  maxTokens: number | null; // null = provider default
  numCtx: number | null;
  think: boolean | null;
  systemPrompt: string;
  skillIds: string[];
  tools: ToolSelection[];
  maxToolCalls: number;
  runTimeoutS: number;
}

export type AgentFormErrors = Partial<Record<keyof AgentFormValues, string>>;

export const LIMITS = {
  maxToolCalls: { min: 1, max: 20 },
  runTimeoutS: { min: 5, max: 300 },
  nameMax: 100,
  descriptionMax: 500,
  systemPromptMax: 20_000,
} as const;

export function emptyAgentForm(): AgentFormValues {
  return {
    name: "",
    description: "",
    provider: "ollama",
    connectionId: null,
    model: "",
    temperature: null,
    maxTokens: null,
    numCtx: null,
    think: null,
    systemPrompt: "You are a helpful assistant. Use the available tools when they help answer accurately.",
    skillIds: [],
    tools: [],
    maxToolCalls: 8,
    runTimeoutS: 120,
  };
}

export function fromAgent(agent: Agent): AgentFormValues {
  return {
    name: agent.name,
    description: agent.description,
    provider: agent.provider,
    connectionId: agent.connection_id ?? null,
    model: agent.model,
    temperature: agent.model_params.temperature ?? null,
    maxTokens: agent.model_params.max_tokens ?? null,
    numCtx: agent.model_params.num_ctx ?? null,
    think: agent.model_params.think ?? null,
    systemPrompt: agent.system_prompt,
    skillIds: agent.skills.map((s) => s.id),
    tools: agent.tools.map((t) => ({ name: t.name, config: { ...t.config } })),
    maxToolCalls: agent.max_tool_calls,
    runTimeoutS: agent.run_timeout_s,
  };
}

export function toAgentWrite(values: AgentFormValues): AgentWrite {
  const params: AgentWrite["model_params"] = {};
  if (values.temperature !== null) params.temperature = values.temperature;
  if (values.maxTokens !== null) params.max_tokens = values.maxTokens;
  // Context size and thinking are Ollama settings; never send them to other providers.
  const ollama = values.connectionId === null ? values.provider === "ollama" : false;
  if (ollama && values.numCtx !== null) params.num_ctx = values.numCtx;
  if (ollama && values.think !== null) params.think = values.think;
  return {
    name: values.name.trim(),
    description: values.description.trim(),
    provider: values.provider,
    connection_id: values.connectionId,
    model: values.model.trim(),
    model_params: params,
    system_prompt: values.systemPrompt,
    skill_ids: values.skillIds,
    tools: values.tools,
    max_tool_calls: values.maxToolCalls,
    run_timeout_s: values.runTimeoutS,
  };
}

const inRange = (n: number, { min, max }: { min: number; max: number }) =>
  Number.isInteger(n) && n >= min && n <= max;

export function validateAgentForm(
  values: AgentFormValues,
  options: { modelSupportsTools?: boolean | null } = {},
): AgentFormErrors {
  const errors: AgentFormErrors = {};
  if (!values.name.trim()) errors.name = "Give your agent a name.";
  else if (values.name.length > LIMITS.nameMax)
    errors.name = `Keep the name under ${LIMITS.nameMax} characters.`;
  if (values.description.length > LIMITS.descriptionMax)
    errors.description = `Keep the description under ${LIMITS.descriptionMax} characters.`;
  if (!values.model.trim()) errors.model = "Choose a model.";
  if (values.systemPrompt.length > LIMITS.systemPromptMax)
    errors.systemPrompt = `Instructions are limited to ${LIMITS.systemPromptMax.toLocaleString()} characters.`;
  if (values.temperature !== null && (values.temperature < 0 || values.temperature > 2))
    errors.temperature = "Temperature must be between 0 and 2.";
  if (values.maxTokens !== null && (!Number.isInteger(values.maxTokens) || values.maxTokens < 1 || values.maxTokens > 200_000))
    errors.maxTokens = "Use a whole number from 1 to 200,000.";
  if (!inRange(values.maxToolCalls, LIMITS.maxToolCalls))
    errors.maxToolCalls = `Use a whole number from ${LIMITS.maxToolCalls.min} to ${LIMITS.maxToolCalls.max}.`;
  if (!inRange(values.runTimeoutS, LIMITS.runTimeoutS))
    errors.runTimeoutS = `Use a whole number from ${LIMITS.runTimeoutS.min} to ${LIMITS.runTimeoutS.max} seconds.`;
  if (values.tools.length > 0 && options.modelSupportsTools === false)
    errors.tools = "The selected model does not support tool calling. Remove the tools or pick another model.";
  return errors;
}
