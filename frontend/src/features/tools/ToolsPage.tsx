import { Clock, ShieldCheck } from "lucide-react";

import { errorMessage } from "../../api/client";
import { useTools } from "../../api/queries";
import type { JsonSchema, ToolInfo } from "../../api/types";
import { ToolIcon } from "../../components/ToolIcon";
import { prettyToolName } from "../../lib/tools";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { PageHeader } from "../../layout/PageHeader";
import { roleAtLeast, useAuth } from "../auth/auth-context";
import { CustomToolsSection, McpServersSection } from "./ToolSources";

export function ToolsPage() {
  const { data: tools, isPending, isError, error, refetch } = useTools();
  const { role } = useAuth();
  const canManage = roleAtLeast(role, "admin");
  return (
    <>
      <PageHeader
        title="Tool library"
        description="Capabilities agents can be granted. Enable them per agent in the agent editor."
      />
      <div className="mb-6 flex items-start gap-3 rounded-2xl border border-emerald-500/25 bg-emerald-500/5 p-4 text-sm">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <p className="text-muted">
          <span className="font-medium text-fg">Safe by design.</span> Every call is checked against
          the agent's permissions, its arguments are validated, and it runs with a timeout and a
          per-run call limit. No tool can run arbitrary code or access files outside the workspace.
          MCP and HTTP tools are off until an admin enables them, and their output is treated as untrusted data.
        </p>
      </div>

      {isError && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {isPending && (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-56 rounded-2xl" />
          <Skeleton className="h-56 rounded-2xl" />
        </div>
      )}
      {tools && (
        <ul className="grid gap-4 md:grid-cols-2" aria-label="Tool library">
          {tools.map((tool) => (
            <li key={tool.name}>
              <ToolCard tool={tool} />
            </li>
          ))}
        </ul>
      )}
      <McpServersSection canManage={canManage} />
      <CustomToolsSection canManage={canManage} />
    </>
  );
}

function ToolCard({ tool }: { tool: ToolInfo }) {
  return (
    <Card className="h-full p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 text-white shadow-md shadow-brand-500/30">
          <ToolIcon name={tool.name} className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{prettyToolName(tool.name)}</h2>
            <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
              {tool.name}
            </code>
            {tool.source && tool.source !== "native" && (
              <Badge tone="violet">{tool.source === "mcp" ? "MCP" : "HTTP"}</Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-muted">{tool.description}</p>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-1.5 text-xs text-subtle">
        <Clock className="size-3.5" /> Times out after {tool.timeout_s}s
      </div>
      <SchemaTable title="Arguments (provided by the model)" schema={tool.args_schema} />
      <SchemaTable title="Per-agent configuration" schema={tool.config_schema} empty="No configuration." />
    </Card>
  );
}

function SchemaTable({ title, schema, empty }: { title: string; schema: JsonSchema; empty?: string }) {
  const entries = Object.entries(schema.properties ?? {});
  if (entries.length === 0 && !empty) return null;
  return (
    <div className="mt-4">
      <p className="mb-1.5 text-[11px] font-semibold tracking-wider text-subtle uppercase">{title}</p>
      {entries.length === 0 ? (
        <p className="text-sm text-muted">{empty}</p>
      ) : (
        <dl className="divide-y divide-line rounded-xl border border-line">
          {entries.map(([key, prop]) => (
            <div key={key} className="px-3 py-2">
              <dt className="flex items-center gap-2">
                <code className="font-mono text-[13px] font-medium">{key}</code>
                <span className="text-[11px] text-subtle">{prop.type}</span>
                {schema.required?.includes(key) && <Badge tone="brand">required</Badge>}
              </dt>
              {prop.description && <dd className="mt-0.5 text-xs text-muted">{prop.description}</dd>}
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
