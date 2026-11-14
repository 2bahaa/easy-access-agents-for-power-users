import type { Agent, ModelInfo, SkillSummary, ToolInfo } from "../api/types";

export const tools: ToolInfo[] = [
  {
    name: "calculator",
    description: "Evaluate an arithmetic expression exactly.",
    args_schema: {
      type: "object",
      properties: { expression: { type: "string", description: "Arithmetic expression" } },
      required: ["expression"],
    },
    config_schema: { type: "object", properties: {} },
    timeout_s: 2,
  },
  {
    name: "file_reader",
    description: "Read a UTF-8 text file from the workspace.",
    args_schema: {
      type: "object",
      properties: { path: { type: "string" } },
      required: ["path"],
    },
    config_schema: {
      type: "object",
      properties: {
        subdir: {
          type: "string",
          title: "Subfolder",
          default: "",
          examples: ["notes"],
          description: "Limit this agent to a subfolder.",
        },
      },
    },
    timeout_s: 5,
  },
];

export const models: ModelInfo[] = [
  { name: "qwen3:4b", size: 2_600_000_000, supports_tools: true, supports_thinking: true },
  { name: "gemma:2b", size: 1_700_000_000, supports_tools: false, supports_thinking: false },
];

export const skills: SkillSummary[] = [
  {
    id: "s-concise",
    slug: "concise-answers",
    name: "Concise answers",
    description: "Keep replies short.",
    is_builtin: true,
    updated_at: "2026-11-14T10:00:00Z",
  },
  {
    id: "s-cite",
    slug: "cite-sources",
    name: "Cite sources",
    description: "Say where facts came from.",
    is_builtin: false,
    updated_at: "2026-11-14T10:00:00Z",
  },
  {
    id: "s-steps",
    slug: "step-by-step",
    name: "Step by step",
    description: "Show your work.",
    is_builtin: false,
    updated_at: "2026-11-14T10:00:00Z",
  },
];

export const agent: Agent = {
  id: "a-1",
  name: "Research Assistant",
  description: "Reads my notes",
  provider: "ollama",
  model: "qwen3:4b",
  model_params: { temperature: 0.3, num_ctx: 8192, think: null },
  system_prompt: "Be careful.",
  skills: [{ id: "s-cite", slug: "cite-sources", name: "Cite sources" }],
  tools: [{ name: "file_reader", config: { subdir: "notes" } }],
  max_tool_calls: 6,
  run_timeout_s: 90,
  created_at: "2026-11-14T10:00:00Z",
  updated_at: "2026-11-14T11:00:00Z",
};
