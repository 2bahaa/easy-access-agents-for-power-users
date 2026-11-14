import type { ModelInfo } from "../api/types";
import { LIMITS, type AgentFormValues } from "./agentForm";

/**
 * Settings to adjust when the user picks a model, based on its capabilities.
 *
 * Rationale (measured on local Ollama):
 * - Thinking models (e.g. qwen3) write long reasoning before answering. With thinking
 *   explicitly ON it is streamed separately (run timeline); with it off or at the model
 *   default it can leak into the visible answer.
 * - Thinking and large models answer slowly, especially on CPU-only machines, so the
 *   default 120 s run timeout is too short.
 * - A model without tool support cannot use any tool.
 */

export interface ModelAdjustment {
  field: "think" | "runTimeoutS" | "tools";
  from: AgentFormValues[ModelAdjustment["field"]];
  to: AgentFormValues[ModelAdjustment["field"]];
  /** Short description of the new value, e.g. "Thinking: On". */
  label: string;
  reason: string;
}

/** Models at least this big are treated as slow. */
export const LARGE_MODEL_BYTES = 4 * 1024 ** 3;

export function modelAdjustments(
  model: ModelInfo | undefined,
  values: AgentFormValues,
): ModelAdjustment[] {
  if (!model) return []; // unknown model (e.g. typed name, Ollama offline): change nothing
  const changes: ModelAdjustment[] = [];

  if (model.supports_thinking && values.think !== true) {
    changes.push({
      field: "think",
      from: values.think,
      to: true,
      label: "Thinking: On",
      reason: "keeps the model's reasoning in the run timeline instead of the answer",
    });
  } else if (!model.supports_thinking && values.think !== null) {
    changes.push({
      field: "think",
      from: values.think,
      to: null,
      label: "Thinking: model default",
      reason: "this model has no thinking mode",
    });
  }

  const slow = model.supports_thinking || (model.size ?? 0) >= LARGE_MODEL_BYTES;
  const maxTimeout = LIMITS.runTimeoutS.max;
  if (slow && values.runTimeoutS < maxTimeout) {
    changes.push({
      field: "runTimeoutS",
      from: values.runTimeoutS,
      to: maxTimeout,
      label: `Run timeout: ${maxTimeout} s`,
      reason: model.supports_thinking
        ? "thinking models take longer to answer"
        : "large models answer more slowly",
    });
  }

  if (!model.supports_tools && values.tools.length > 0) {
    changes.push({
      field: "tools",
      from: values.tools,
      to: [],
      label: "Tools: removed",
      reason: "this model cannot call tools",
    });
  }

  return changes;
}

export function applyAdjustments(
  values: AgentFormValues,
  changes: ModelAdjustment[],
): AgentFormValues {
  return changes.reduce<AgentFormValues>((v, c) => ({ ...v, [c.field]: c.to }), values);
}

export function revertAdjustments(
  values: AgentFormValues,
  changes: ModelAdjustment[],
): AgentFormValues {
  return changes.reduce<AgentFormValues>((v, c) => ({ ...v, [c.field]: c.from }), values);
}
