import type { AgentWrite } from "../api/types";

export interface FieldChange {
  field: string;
  label: string;
  before: string;
  after: string;
}

const LABELS: Record<string, string> = {
  name: "Name",
  description: "Description",
  provider: "Provider",
  connection_id: "Provider connection",
  model: "Model",
  model_params: "Model parameters",
  system_prompt: "Instructions",
  skill_ids: "Skills",
  tools: "Tools",
  max_tool_calls: "Max tool calls",
  run_timeout_s: "Run timeout",
};

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, Object.keys(value as object).sort());
}

function normalize(value: unknown): unknown {
  // Treat missing/null model params the same (the API returns every key).
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v !== null && v !== undefined)
        .sort(([a], [b]) => a.localeCompare(b)),
    );
  }
  return value ?? null;
}

/** Field-level differences between two agent configurations (e.g. a version vs the draft). */
export function diffAgentConfigs(before: Partial<AgentWrite>, after: Partial<AgentWrite>): FieldChange[] {
  const fields = Object.keys(LABELS);
  const changes: FieldChange[] = [];
  for (const field of fields) {
    const a = normalize((before as Record<string, unknown>)[field]);
    const b = normalize((after as Record<string, unknown>)[field]);
    if (JSON.stringify(a) !== JSON.stringify(b)) {
      changes.push({ field, label: LABELS[field] ?? field, before: show(a), after: show(b) });
    }
  }
  return changes;
}
