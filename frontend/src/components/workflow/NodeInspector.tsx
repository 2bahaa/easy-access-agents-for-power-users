import { Plus, X } from "lucide-react";

import type { ProviderInfo, ToolInfo, WorkflowNodeType } from "../../api/types";
import { NODE_META } from "../../lib/workflowGraph";
import { Button } from "../ui/Button";
import { Field, Input, Select, Textarea } from "../ui/Field";

export interface WorkflowCatalogs {
  agents: Array<{ id: string; name: string }>;
  tools: ToolInfo[];
  collections: Array<{ id: string; name: string }>;
  providers: ProviderInfo[];
}

export interface NodeInspectorProps {
  id: string;
  type: WorkflowNodeType;
  label: string;
  config: Record<string, unknown>;
  retries?: number;
  onError?: "fail" | "continue";
  catalogs: WorkflowCatalogs;
  onChange: (patch: { label?: string; config?: Record<string, unknown>; retries?: number; onError?: "fail" | "continue" }) => void;
  problems?: string[];
  /** Last run output of this node (debugging). */
  output?: string;
  error?: string;
}

const str = (v: unknown) => (typeof v === "string" ? v : "");

/** Per-type configuration form for the selected node (prop-driven). */
export function NodeInspector({ id, type, label, config, retries = 0, onError = "fail", catalogs, onChange, problems = [], output, error }: NodeInspectorProps) {
  const set = (key: string, value: unknown) => onChange({ config: { ...config, [key]: value } });
  const meta = NODE_META[type];
  const providerSelect = (
    <Field label="Model provider">
      {(p) => (
        <Select
          {...p}
          value={str(config.connection_id) || str(config.provider) || "ollama"}
          onChange={(e) => {
            const prov = catalogs.providers.find((x) => x.name === e.target.value);
            onChange({ config: { ...config, provider: prov?.builtin ? prov.name : "ollama", connection_id: prov && !prov.builtin ? prov.name : null } });
          }}
        >
          {catalogs.providers.map((p) => (
            <option key={p.name} value={p.name}>
              {p.label}
            </option>
          ))}
        </Select>
      )}
    </Field>
  );
  const modelField = <Field label="Model">{(p) => <Input {...p} value={str(config.model)} onChange={(e) => set("model", e.target.value)} />}</Field>;
  const templateHint = "Use {{ node_id }} for an earlier step's output and {{ input.name }} for inputs.";

  return (
    <div className="space-y-4" aria-label={`Configure ${id}`}>
      <div>
        <p className="text-xs font-semibold tracking-wider text-subtle uppercase">{meta.title}</p>
        <p className="text-xs text-muted">{meta.description}</p>
        <p className="mt-1 font-mono text-[11px] text-subtle">id: {id}</p>
      </div>
      {problems.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-danger/30 bg-danger/5 p-2 text-xs text-danger" aria-label="Problems">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <Field label="Label">{(p) => <Input {...p} value={label} onChange={(e) => onChange({ label: e.target.value })} />}</Field>

      {type === "start" && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Inputs</legend>
          {((config.inputs as Array<{ name: string; description: string }>) ?? []).map((inp, i, all) => (
            <div key={i} className="flex gap-2">
              <Input aria-label={`Input ${i + 1} name`} value={inp.name} onChange={(e) => set("inputs", all.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <Button size="sm" variant="ghost" aria-label={`Remove input ${i + 1}`} icon={<X className="size-4" />} onClick={() => set("inputs", all.filter((_, j) => j !== i))} />
            </div>
          ))}
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => set("inputs", [...((config.inputs as unknown[]) ?? []), { name: "", description: "" }])}>
            Add input
          </Button>
        </fieldset>
      )}
      {type === "end" && (
        <Field label="Output" hint={templateHint}>
          {(p) => <Textarea {...p} rows={4} value={str(config.output)} onChange={(e) => set("output", e.target.value)} />}
        </Field>
      )}
      {(type === "agent" || type === "memory") && (
        <Field label="Agent">
          {(p) => (
            <Select {...p} value={str(config.agent_id)} onChange={(e) => set("agent_id", e.target.value)}>
              <option value="">Choose an agent…</option>
              {catalogs.agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      )}
      {type === "agent" && (
        <>
          <Field label="Prompt" hint={templateHint}>
            {(p) => <Textarea {...p} rows={5} value={str(config.prompt)} onChange={(e) => set("prompt", e.target.value)} />}
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!config.use_draft} onChange={(e) => set("use_draft", e.target.checked)} /> Use the agent's draft (not the published version)
          </label>
        </>
      )}
      {type === "memory" && (
        <>
          <Field label="Action">
            {(p) => (
              <Select {...p} value={str(config.action) || "search"} onChange={(e) => set("action", e.target.value)}>
                <option value="search">Search memories</option>
                <option value="save">Save a memory</option>
              </Select>
            )}
          </Field>
          <Field label="Text" hint={templateHint}>{(p) => <Input {...p} value={str(config.text)} onChange={(e) => set("text", e.target.value)} />}</Field>
        </>
      )}
      {(type === "llm" || type === "router" || type === "supervisor") && (
        <>
          {providerSelect}
          {modelField}
        </>
      )}
      {type === "llm" && (
        <>
          <Field label="System prompt">{(p) => <Textarea {...p} rows={3} value={str(config.system)} onChange={(e) => set("system", e.target.value)} />}</Field>
          <Field label="Prompt" hint={templateHint}>{(p) => <Textarea {...p} rows={5} value={str(config.prompt)} onChange={(e) => set("prompt", e.target.value)} />}</Field>
        </>
      )}
      {type === "router" && (
        <>
          <Field label="Routes" hint="Comma-separated labels; each becomes a branch.">
            {(p) => (
              <Input
                {...p}
                value={((config.routes as string[]) ?? []).join(", ")}
                onChange={(e) => set("routes", e.target.value.split(",").map((r) => r.trim()))}
              />
            )}
          </Field>
          <Field label="Instructions">{(p) => <Textarea {...p} rows={2} value={str(config.instructions)} onChange={(e) => set("instructions", e.target.value)} />}</Field>
          <Field label="Input to classify" hint={templateHint}>{(p) => <Input {...p} value={str(config.input)} onChange={(e) => set("input", e.target.value)} />}</Field>
        </>
      )}
      {type === "tool" && (
        <>
          <Field label="Tool">
            {(p) => (
              <Select {...p} value={str(config.tool)} onChange={(e) => onChange({ config: { ...config, tool: e.target.value, args: {}, config: {} } })}>
                {catalogs.tools
                  .filter((t) => t.source !== "knowledge" && t.source !== "memory")
                  .map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
              </Select>
            )}
          </Field>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Arguments</legend>
            {Object.keys(catalogs.tools.find((t) => t.name === config.tool)?.args_schema.properties ?? {}).map((arg) => (
              <Field key={arg} label={arg} hint="Template">
                {(p) => (
                  <Input
                    {...p}
                    value={str((config.args as Record<string, string> | undefined)?.[arg])}
                    onChange={(e) => set("args", { ...((config.args as Record<string, string>) ?? {}), [arg]: e.target.value })}
                  />
                )}
              </Field>
            ))}
          </fieldset>
        </>
      )}
      {type === "knowledge" && (
        <>
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">Collections</legend>
            {catalogs.collections.length === 0 && <p className="text-xs text-warning">Create a collection on the Knowledge page.</p>}
            {catalogs.collections.map((c) => {
              const ids = (config.collection_ids as string[]) ?? [];
              return (
                <label key={c.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={ids.includes(c.id)} onChange={(e) => set("collection_ids", e.target.checked ? [...ids, c.id] : ids.filter((x) => x !== c.id))} />
                  {c.name}
                </label>
              );
            })}
          </fieldset>
          <Field label="Query" hint={templateHint}>{(p) => <Input {...p} value={str(config.query)} onChange={(e) => set("query", e.target.value)} />}</Field>
        </>
      )}
      {type === "condition" && (
        <Field label="Expression" hint='e.g. contains(classify, "urgent") and len(summary) > 50 — node ids and input_<name> are available.'>
          {(p) => <Input {...p} className="font-mono" value={str(config.expression)} onChange={(e) => set("expression", e.target.value)} />}
        </Field>
      )}
      {type === "approval" && (
        <Field label="Message for the reviewer" hint={templateHint}>
          {(p) => <Textarea {...p} rows={3} value={str(config.message)} onChange={(e) => set("message", e.target.value)} />}
        </Field>
      )}
      {type === "supervisor" && (
        <>
          <Field label="Team task" hint={templateHint}>{(p) => <Textarea {...p} rows={3} value={str(config.task)} onChange={(e) => set("task", e.target.value)} />}</Field>
          <Field label="Supervisor instructions">{(p) => <Textarea {...p} rows={2} value={str(config.instructions)} onChange={(e) => set("instructions", e.target.value)} />}</Field>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Members</legend>
            {((config.members as Array<{ name: string; agent_id: string; role: string }>) ?? []).map((m, i, all) => {
              const update = (patch: Partial<typeof m>) => set("members", all.map((x, j) => (j === i ? { ...x, ...patch } : x)));
              return (
                <div key={i} className="space-y-1 rounded-lg border border-line p-2">
                  <div className="flex gap-2">
                    <Input aria-label={`Member ${i + 1} name`} placeholder="name" value={m.name} onChange={(e) => update({ name: e.target.value })} />
                    <Button size="sm" variant="ghost" aria-label={`Remove member ${i + 1}`} icon={<X className="size-4" />} onClick={() => set("members", all.filter((_, j) => j !== i))} />
                  </div>
                  <Select aria-label={`Member ${i + 1} agent`} value={m.agent_id} onChange={(e) => update({ agent_id: e.target.value })}>
                    <option value="">Choose an agent…</option>
                    {catalogs.agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </Select>
                  <Input aria-label={`Member ${i + 1} role`} placeholder="What this member is good at" value={m.role} onChange={(e) => update({ role: e.target.value })} />
                </div>
              );
            })}
            <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => set("members", [...((config.members as unknown[]) ?? []), { name: `member${((config.members as unknown[]) ?? []).length + 1}`, agent_id: "", role: "" }])}>
              Add member
            </Button>
          </fieldset>
          <Field label="Max delegations" hint="Hard budget (1-20) for how many tasks the supervisor may hand out.">
            {(p) => <Input {...p} type="number" min={1} max={20} value={Number(config.max_delegations ?? 4)} onChange={(e) => set("max_delegations", Number(e.target.value))} />}
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!config.share_task_with_members} onChange={(e) => set("share_task_with_members", e.target.checked)} /> Share the overall task with members
          </label>
        </>
      )}
      {type !== "start" && type !== "end" && (
        <fieldset className="grid grid-cols-2 gap-2">
          <legend className="mb-1 text-sm font-medium">On failure</legend>
          <Field label="Retries">
            {(p) => <Input {...p} type="number" min={0} max={3} value={retries} onChange={(e) => onChange({ retries: Math.max(0, Math.min(3, Number(e.target.value))) })} />}
          </Field>
          <Field label="Then">
            {(p) => (
              <Select {...p} value={onError} onChange={(e) => onChange({ onError: e.target.value as "fail" | "continue" })}>
                <option value="fail">Fail the run</option>
                <option value="continue">Continue (empty output)</option>
              </Select>
            )}
          </Field>
        </fieldset>
      )}
      {(output || error) && (
        <div>
          <p className="mb-1 text-xs font-semibold tracking-wider text-subtle uppercase">Last run</p>
          {error ? (
            <p className="rounded-lg bg-danger/10 p-2 text-xs text-danger">{error}</p>
          ) : (
            <pre className="max-h-48 overflow-auto rounded-lg bg-surface-2 p-2 text-xs whitespace-pre-wrap">{output}</pre>
          )}
        </div>
      )}
    </div>
  );
}
