import { AlertTriangle, Brain, Check, Cpu, Wrench } from "lucide-react";

import type { ModelInfo } from "../api/types";
import { cn } from "../lib/cn";
import { formatBytes } from "../lib/format";
import { Badge } from "./ui/Badge";
import { Input } from "./ui/Field";
import { Skeleton } from "./ui/States";

export interface ModelPickerProps {
  models: ModelInfo[] | undefined;
  value: string;
  onChange: (model: string) => void;
  loading?: boolean;
  /** Set when the model list could not be loaded (e.g. Ollama offline). */
  unavailableMessage?: string;
  invalid?: boolean;
}

/** Choose a model, showing tool-calling and thinking support for each. */
export function ModelPicker({
  models,
  value,
  onChange,
  loading,
  unavailableMessage,
  invalid,
}: ModelPickerProps) {
  if (loading) {
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
    );
  }

  if (unavailableMessage || !models) {
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{unavailableMessage ?? "Model list unavailable."} You can still type a model name.</span>
        </div>
        <Input
          aria-label="Model name"
          aria-invalid={invalid || undefined}
          placeholder="e.g. qwen3:4b"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }

  const known = models.some((m) => m.name === value);

  return (
    <div className="space-y-2">
      <div
        role="radiogroup"
        aria-label="Model"
        aria-invalid={invalid || undefined}
        className={cn(
          "scrollbar-thin max-h-72 space-y-1.5 overflow-y-auto rounded-xl p-0.5",
          invalid && "ring-2 ring-red-500/40",
        )}
      >
        {models.length === 0 && (
          <p className="rounded-xl border border-dashed border-line-strong p-4 text-center text-sm text-muted">
            No models installed. Pull one with <code className="font-mono">ollama pull qwen3:4b</code>.
          </p>
        )}
        {models.map((m) => {
          const selected = m.name === value;
          return (
            <button
              key={m.name}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(m.name)}
              className={cn(
                "group flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all",
                selected
                  ? "border-brand-500 bg-brand-500/5 ring-4 ring-brand-500/10"
                  : "border-line bg-surface hover:border-line-strong hover:bg-surface-2",
              )}
            >
              <span
                className={cn(
                  "grid size-8 shrink-0 place-items-center rounded-lg transition-colors",
                  selected
                    ? "bg-gradient-to-br from-brand-500 to-accent-500 text-white"
                    : "bg-surface-2 text-muted group-hover:text-fg",
                )}
              >
                {selected ? <Check className="size-4" /> : <Cpu className="size-4" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-[13px] font-medium">{m.name}</span>
                <span className="mt-1 flex flex-wrap items-center gap-1">
                  {m.supports_tools === true ? (
                    <Badge tone="success" icon={<Wrench />}>
                      Tools
                    </Badge>
                  ) : m.supports_tools === false ? (
                    <Badge tone="neutral">No tools</Badge>
                  ) : (
                    <Badge tone="warning">Tools: unknown</Badge>
                  )}
                  {m.context_window ? (
                    <span className="text-[11px] text-subtle">{Math.round(m.context_window / 1000)}k ctx</span>
                  ) : null}
                  {m.supports_thinking && (
                    <Badge tone="violet" icon={<Brain />}>
                      Thinking
                    </Badge>
                  )}
                  {m.size ? <span className="text-[11px] text-subtle">{formatBytes(m.size)}</span> : null}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {value && !known && (
        <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="size-3.5" />
          <span>
            <code className="font-mono">{value}</code> is not installed in Ollama.
          </span>
        </p>
      )}
    </div>
  );
}
