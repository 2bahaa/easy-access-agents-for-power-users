import {
  AlertCircle,
  BookOpen,
  Cpu,
  Gauge,
  MessageSquareText,
  RotateCcw,
  Save,
  Sparkles,
  Undo2,
  Wand2,
  Wrench,
} from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";

import type { AgentWrite, ModelInfo, ProviderInfo, SkillSummary, ToolInfo } from "../api/types";
import {
  LIMITS,
  toAgentWrite,
  validateAgentForm,
  type AgentFormErrors,
  type AgentFormValues,
} from "../lib/agentForm";
import { cn } from "../lib/cn";
import {
  applyAdjustments,
  modelAdjustments,
  revertAdjustments,
  type ModelAdjustment,
} from "../lib/modelDefaults";
import { ModelPicker } from "./ModelPicker";
import { SkillSelector } from "./SkillSelector";
import { ToolPicker } from "./ToolPicker";
import { Button } from "./ui/Button";
import { Section } from "./ui/Card";
import { Field, Input, Select, Textarea } from "./ui/Field";

/** API field name -> form field, for server-side validation messages. */
const SERVER_FIELDS: Record<string, keyof AgentFormValues> = {
  name: "name",
  description: "description",
  model: "model",
  temperature: "temperature",
  num_ctx: "numCtx",
  max_tokens: "maxTokens",
  system_prompt: "systemPrompt",
  max_tool_calls: "maxToolCalls",
  run_timeout_s: "runTimeoutS",
  tools: "tools",
};

const CONTEXT_SIZES = [2048, 4096, 8192, 16384, 32768, 65536];

export interface AgentBuilderProps {
  initialValues: AgentFormValues;
  /** Knowledge collections (for the knowledge search tool). */
  collections?: Array<{ id: string; name: string }>;
  /** Providers the agent can run on (built-ins and workspace connections). */
  providers?: ProviderInfo[];
  /** Called with the provider ref (`name`) whose models should be loaded. */
  onProviderChange?: (provider: string) => void;
  models?: ModelInfo[];
  modelsLoading?: boolean;
  modelsUnavailable?: string;
  skills: SkillSummary[];
  tools: ToolInfo[];
  onSubmit: (data: AgentWrite) => void;
  submitting?: boolean;
  /** Top-level error from the last save attempt. */
  serverError?: string | null;
  /** Field errors from the last save attempt, keyed by API field name. */
  serverFieldErrors?: Record<string, string>;
  submitLabel?: string;
  /** True when creating a new agent (changes the status text). */
  isNew?: boolean;
  /** Extra buttons for the action bar (e.g. Delete). */
  secondaryActions?: ReactNode;
  emptySkillsAction?: ReactNode;
}

/**
 * Complete agent editor: identity, model, instructions, skills, tools and limits.
 * Prop-driven (no data fetching) so it can be reused outside the Studio.
 */
export function AgentBuilder({
  initialValues,
  collections,
  providers,
  onProviderChange,
  models,
  modelsLoading,
  modelsUnavailable,
  skills,
  tools,
  onSubmit,
  submitting,
  serverError,
  serverFieldErrors,
  submitLabel = "Save agent",
  isNew = false,
  secondaryActions,
  emptySkillsAction,
}: AgentBuilderProps) {
  const [values, setValues] = useState<AgentFormValues>(initialValues);
  const [errors, setErrors] = useState<AgentFormErrors>({});
  const [submitted, setSubmitted] = useState(false);
  /** Settings changed automatically by the last model selection (shown with Undo). */
  const [adjusted, setAdjusted] = useState<{ model: string; changes: ModelAdjustment[] } | null>(
    null,
  );

  const selectedModel = models?.find((m) => m.name === values.model);
  const providerRef = values.connectionId ?? values.provider;
  const currentProvider = providers?.find((p) => p.name === providerRef);
  const isOllama = values.connectionId === null ? values.provider === "ollama" : currentProvider?.kind === "ollama";

  /** Switching provider clears the model (names are provider-specific). */
  const selectProvider = (ref: string) => {
    const p = providers?.find((x) => x.name === ref);
    if (!p) return;
    update({ ...values, provider: p.builtin ? p.name : p.kind, connectionId: p.builtin ? null : p.name, model: "" });
    setAdjusted(null);
    onProviderChange?.(ref);
  };
  const supportsTools = selectedModel?.supports_tools;
  const dirty = useMemo(
    () => JSON.stringify(values) !== JSON.stringify(initialValues),
    [values, initialValues],
  );

  const mergedErrors: AgentFormErrors = { ...errors };
  for (const [apiField, message] of Object.entries(serverFieldErrors ?? {})) {
    const field = SERVER_FIELDS[apiField];
    if (field && !mergedErrors[field]) mergedErrors[field] = message;
  }

  const modelSupport = (v: AgentFormValues) =>
    models?.find((m) => m.name === v.model)?.supports_tools;

  const update = (next: AgentFormValues) => {
    setValues(next);
    if (submitted) setErrors(validateAgentForm(next, { modelSupportsTools: modelSupport(next) }));
  };

  const set = <K extends keyof AgentFormValues>(key: K, value: AgentFormValues[K]) =>
    update({ ...values, [key]: value });

  /** Choosing a model also applies the settings that model needs (undoable). */
  const selectModel = (name: string) => {
    const next = { ...values, model: name };
    const changes = modelAdjustments(
      models?.find((m) => m.name === name),
      next,
    );
    update(applyAdjustments(next, changes));
    setAdjusted(changes.length > 0 ? { model: name, changes } : null);
  };

  const undoAdjustments = () => {
    if (!adjusted) return;
    update(revertAdjustments(values, adjusted.changes));
    setAdjusted(null);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    const found = validateAgentForm(values, { modelSupportsTools: supportsTools });
    setErrors(found);
    if (Object.keys(found).length === 0) onSubmit(toAgentWrite(values));
  };

  const errorCount = Object.keys(mergedErrors).length;

  return (
    <form onSubmit={handleSubmit} noValidate aria-label="Agent configuration" className="pb-24">
      {serverError && (
        <div
          role="alert"
          className="mb-5 flex items-start gap-2.5 rounded-2xl border border-red-500/25 bg-red-500/5 p-4 text-sm text-red-700 dark:text-red-300"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{serverError}</span>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          <Section
            title="Identity"
            description="How this agent appears in the Studio."
            icon={<Sparkles />}
          >
            <div className="space-y-4">
              <Field label="Name" required error={mergedErrors.name}>
                {(a11y) => (
                  <Input
                    {...a11y}
                    value={values.name}
                    maxLength={LIMITS.nameMax}
                    placeholder="e.g. Research assistant"
                    onChange={(e) => set("name", e.target.value)}
                  />
                )}
              </Field>
              <Field
                label="Description"
                error={mergedErrors.description}
                hint="Optional. A one-line summary of what the agent is for."
              >
                {(a11y) => (
                  <Input
                    {...a11y}
                    value={values.description}
                    maxLength={LIMITS.descriptionMax}
                    placeholder="Answers questions using my notes and exact math"
                    onChange={(e) => set("description", e.target.value)}
                  />
                )}
              </Field>
            </div>
          </Section>

          <Section
            title="Instructions"
            description="The system prompt that defines the agent's role and behavior."
            icon={<MessageSquareText />}
          >
            <Field
              label="System prompt"
              error={mergedErrors.systemPrompt}
              trailing={
                <span className="text-xs text-subtle tabular-nums">
                  {values.systemPrompt.length.toLocaleString()} /{" "}
                  {LIMITS.systemPromptMax.toLocaleString()}
                </span>
              }
            >
              {(a11y) => (
                <Textarea
                  {...a11y}
                  rows={9}
                  value={values.systemPrompt}
                  placeholder="You are a precise assistant…"
                  onChange={(e) => set("systemPrompt", e.target.value)}
                  className="font-mono text-[13px]"
                />
              )}
            </Field>
          </Section>

          <Section
            title="Skills"
            description="Reusable Markdown instructions appended to the system prompt, in this order."
            icon={<BookOpen />}
          >
            <SkillSelector
              skills={skills}
              value={values.skillIds}
              onChange={(ids) => set("skillIds", ids)}
              emptyAction={emptySkillsAction}
            />
          </Section>
        </div>

        <div className="space-y-5 lg:col-span-2">
          <Section
            title="Model"
            description={
              currentProvider && !currentProvider.builtin
                ? `Runs on ${currentProvider.label}.`
                : "Runs locally through Ollama."
            }
            icon={<Cpu />}
          >
            <div className="space-y-4">
              {providers && providers.length > 1 && (
                <Field label="Provider">
                  {(a11y) => (
                    <Select {...a11y} value={providerRef} onChange={(e) => selectProvider(e.target.value)}>
                      {providers.map((p) => (
                        <option key={p.name} value={p.name}>
                          {p.label}
                          {p.status === "error" ? " (unreachable)" : ""}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              )}
              <div>
                <ModelPicker
                  models={models}
                  value={values.model}
                  onChange={selectModel}
                  loading={modelsLoading}
                  unavailableMessage={modelsUnavailable}
                  invalid={!!mergedErrors.model}
                />
                {mergedErrors.model && (
                  <p className="mt-1.5 text-xs font-medium text-red-600 dark:text-red-400">
                    {mergedErrors.model}
                  </p>
                )}
                {adjusted && adjusted.model === values.model && (
                  <div
                    role="status"
                    className="mt-3 animate-fade-in rounded-xl border border-brand-500/25 bg-brand-500/5 p-3"
                  >
                    <div className="flex items-start gap-2.5">
                      <Wand2 className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-400" />
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold">
                          Settings adjusted for <span className="font-mono">{adjusted.model}</span>
                        </p>
                        <ul className="mt-1.5 space-y-1">
                          {adjusted.changes.map((c) => (
                            <li key={c.field} className="text-xs text-muted">
                              <span className="font-medium text-fg">{c.label}</span> — {c.reason}
                            </li>
                          ))}
                        </ul>
                      </div>
                      <button
                        type="button"
                        onClick={undoAdjustments}
                        className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-500/10 dark:text-brand-400"
                      >
                        <Undo2 className="size-3.5" /> Undo
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <Field
                label="Temperature"
                error={mergedErrors.temperature}
                hint="Lower is more focused and repeatable; higher is more creative."
                trailing={
                  <span className="flex items-center gap-1.5">
                    <span className="font-mono text-xs text-muted tabular-nums">
                      {values.temperature === null ? "default" : values.temperature.toFixed(2)}
                    </span>
                    {values.temperature !== null && (
                      <button
                        type="button"
                        title="Use model default"
                        aria-label="Reset temperature to model default"
                        onClick={() => set("temperature", null)}
                        className="rounded-md p-0.5 text-subtle hover:bg-surface-2 hover:text-fg"
                      >
                        <RotateCcw className="size-3" />
                      </button>
                    )}
                  </span>
                }
              >
                {(a11y) => (
                  <input
                    {...a11y}
                    type="range"
                    min={0}
                    max={2}
                    step={0.05}
                    value={values.temperature ?? 0.8}
                    onChange={(e) => set("temperature", Number(e.target.value))}
                    className={cn(
                      "h-2 w-full cursor-pointer accent-brand-500",
                      values.temperature === null && "opacity-40",
                    )}
                  />
                )}
              </Field>

              <Field
                label="Max output tokens"
                error={mergedErrors.maxTokens}
                hint="Leave empty for the provider's default."
              >
                {(a11y) => (
                  <Input
                    {...a11y}
                    type="number"
                    min={1}
                    max={200000}
                    placeholder="Default"
                    value={values.maxTokens ?? ""}
                    onChange={(e) => set("maxTokens", e.target.value === "" ? null : e.target.valueAsNumber)}
                  />
                )}
              </Field>

              {isOllama && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Context window">
                  {(a11y) => (
                    <Select
                      {...a11y}
                      value={values.numCtx ?? ""}
                      onChange={(e) =>
                        set("numCtx", e.target.value === "" ? null : Number(e.target.value))
                      }
                    >
                      <option value="">Model default</option>
                      {CONTEXT_SIZES.map((n) => (
                        <option key={n} value={n}>
                          {n.toLocaleString()} tokens
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label="Thinking">
                  {(a11y) => (
                    <Select
                      {...a11y}
                      value={values.think === null ? "" : values.think ? "on" : "off"}
                      disabled={!selectedModel?.supports_thinking && values.think === null}
                      onChange={(e) =>
                        set("think", e.target.value === "" ? null : e.target.value === "on")
                      }
                    >
                      <option value="">Model default</option>
                      <option value="on">On</option>
                      <option value="off">Off</option>
                    </Select>
                  )}
                </Field>
              </div>
              )}
            </div>
          </Section>

          <Section
            title="Tools"
            description="Capabilities the agent may call. Only enabled tools are ever offered to the model."
            icon={<Wrench />}
          >
            <ToolPicker
              tools={tools}
              collections={collections}
              value={values.tools}
              onChange={(next) => set("tools", next)}
              disabledReason={
                supportsTools === false
                  ? `${values.model} does not support tool calling. Choose a model with the Tools badge to enable tools.`
                  : undefined
              }
              warning={
                supportsTools === null && values.model
                  ? `The provider does not report whether ${values.model} can call tools. Run the tool-calling check in Providers before running this agent with tools.`
                  : undefined
              }
            />
            {mergedErrors.tools && (
              <p className="mt-2 text-xs font-medium text-red-600 dark:text-red-400">
                {mergedErrors.tools}
              </p>
            )}
          </Section>

          <Section
            title="Limits"
            description="Safety limits enforced on every run."
            icon={<Gauge />}
          >
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Max tool calls"
                error={mergedErrors.maxToolCalls}
                hint={`${LIMITS.maxToolCalls.min}–${LIMITS.maxToolCalls.max} per run`}
              >
                {(a11y) => (
                  <Input
                    {...a11y}
                    type="number"
                    min={LIMITS.maxToolCalls.min}
                    max={LIMITS.maxToolCalls.max}
                    value={Number.isNaN(values.maxToolCalls) ? "" : values.maxToolCalls}
                    onChange={(e) => set("maxToolCalls", e.target.valueAsNumber)}
                  />
                )}
              </Field>
              <Field
                label="Run timeout (s)"
                error={mergedErrors.runTimeoutS}
                hint={`${LIMITS.runTimeoutS.min}–${LIMITS.runTimeoutS.max} seconds`}
              >
                {(a11y) => (
                  <Input
                    {...a11y}
                    type="number"
                    min={LIMITS.runTimeoutS.min}
                    max={LIMITS.runTimeoutS.max}
                    value={Number.isNaN(values.runTimeoutS) ? "" : values.runTimeoutS}
                    onChange={(e) => set("runTimeoutS", e.target.valueAsNumber)}
                  />
                )}
              </Field>
            </div>
          </Section>
        </div>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/85 backdrop-blur-md lg:left-64">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-8">
          <p className="min-w-0 flex-1 truncate text-sm">
            {errorCount > 0 ? (
              <span className="font-medium text-red-600 dark:text-red-400">
                Please fix {errorCount} {errorCount === 1 ? "field" : "fields"}.
              </span>
            ) : isNew ? (
              <span className="text-muted">New agent · not saved yet</span>
            ) : dirty ? (
              <span className="flex items-center gap-2 text-muted">
                <span className="size-2 rounded-full bg-amber-500" /> Unsaved changes
              </span>
            ) : (
              <span className="text-subtle">All changes saved</span>
            )}
          </p>
          {secondaryActions}
          <Button
            type="submit"
            variant="primary"
            loading={submitting}
            icon={<Save className="size-4" />}
          >
            {submitLabel}
          </Button>
        </div>
      </div>
    </form>
  );
}
