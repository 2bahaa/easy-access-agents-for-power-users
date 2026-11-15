import { AlertTriangle, Clock } from "lucide-react";

import type { ToolInfo, ToolSelection } from "../api/types";
import { cn } from "../lib/cn";
import { hasFields, schemaDefaults } from "../lib/schema";
import { prettyToolName } from "../lib/tools";
import { SchemaFields } from "./SchemaFields";
import { ToolIcon } from "./ToolIcon";
import { Switch } from "./ui/Switch";

export interface ToolPickerProps {
  tools: ToolInfo[];
  value: ToolSelection[];
  onChange: (value: ToolSelection[]) => void;
  /** When set, tools cannot be enabled and this reason is shown. */
  disabledReason?: string;
  /** A non-blocking caution shown above the list (e.g. unknown tool support). */
  warning?: string;
}

/** Enable tools for an agent and edit each tool's per-agent configuration. */
export function ToolPicker({ tools, value, onChange, disabledReason, warning }: ToolPickerProps) {
  const selected = new Map(value.map((t) => [t.name, t]));

  const toggle = (tool: ToolInfo, on: boolean) => {
    onChange(
      on
        ? [...value, { name: tool.name, config: schemaDefaults(tool.config_schema) }]
        : value.filter((t) => t.name !== tool.name),
    );
  };

  const setConfig = (name: string, config: Record<string, unknown>) =>
    onChange(value.map((t) => (t.name === name ? { ...t, config } : t)));

  return (
    <div className="space-y-3">
      {(disabledReason ?? warning) && (
        <div
          role={disabledReason ? undefined : "note"}
          className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{disabledReason ?? warning}</span>
        </div>
      )}
      <ul aria-label="Tools" className="space-y-2">
        {tools.map((tool) => {
          const current = selected.get(tool.name);
          const enabled = !!current;
          const params = Object.keys(tool.args_schema.properties ?? {});
          return (
            <li
              key={tool.name}
              className={cn(
                "rounded-xl border transition-all",
                enabled ? "border-brand-500/40 bg-brand-500/[0.04]" : "border-line bg-surface",
              )}
            >
              <div className="flex items-start gap-3 p-3">
                <span
                  className={cn(
                    "grid size-9 shrink-0 place-items-center rounded-lg transition-colors",
                    enabled
                      ? "bg-gradient-to-br from-brand-500 to-accent-500 text-white shadow-sm shadow-brand-500/30"
                      : "bg-surface-2 text-muted",
                  )}
                >
                  <ToolIcon name={tool.name} className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{prettyToolName(tool.name)}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted">{tool.description}</p>
                  <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-subtle">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="size-3" />
                      {tool.timeout_s}s timeout
                    </span>
                    {params.length > 0 && (
                      <span className="font-mono">({params.join(", ")})</span>
                    )}
                  </p>
                </div>
                <Switch
                  label={`Enable ${prettyToolName(tool.name)}`}
                  checked={enabled}
                  disabled={!enabled && !!disabledReason}
                  onChange={(on) => toggle(tool, on)}
                />
              </div>
              {enabled && hasFields(tool.config_schema) && (
                <div className="animate-fade-in border-t border-brand-500/15 px-3 pt-3 pb-3.5">
                  <SchemaFields
                    idPrefix={`tool-${tool.name}`}
                    schema={tool.config_schema}
                    value={current.config}
                    onChange={(config) => setConfig(tool.name, config)}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
