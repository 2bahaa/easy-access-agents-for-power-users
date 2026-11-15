import { Bot, Cpu, MessageSquare, Plus, Search, Upload } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { errorMessage } from "../../api/client";
import { useAgents, useImportAgent } from "../../api/queries";
import type { AgentExportDocument } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { buttonClasses } from "../../components/ui/buttonStyles";
import { useToast } from "../../components/ui/toast-context";
import { LinkButton } from "../../components/ui/LinkButton";
import { Card } from "../../components/ui/Card";
import { Input } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { PageHeader } from "../../layout/PageHeader";
import { relativeTime } from "../../lib/format";
import { AgentAvatar } from "./AgentAvatar";
import { NewAgentDialog } from "./NewAgentDialog";

export function AgentsPage() {
  const { data: agents, isPending, isError, error, refetch } = useAgents();
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  const importAgent = useImportAgent();

  const importFile = async (file: File) => {
    try {
      const doc = JSON.parse(await file.text()) as AgentExportDocument;
      const result = await importAgent.mutateAsync(doc);
      toast.push({
        title: "Agent imported",
        description: result.created_skills.length ? `New skills: ${result.created_skills.join(", ")}` : undefined,
      });
      navigate(`/agents/${result.agent_id}`);
    } catch (error) {
      toast.push({
        tone: "error",
        title: "Import failed",
        description: error instanceof SyntaxError ? "The file is not valid JSON." : errorMessage(error),
      });
    }
  };
  const filtered = (agents ?? []).filter((a) =>
    `${a.name} ${a.description} ${a.model}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <>
      <PageHeader
        title="Agents"
        description="Create agents, give them skills and tools, and choose the model they run on."
        actions={
          <>
            <label className={buttonClasses({ variant: "secondary" })}>
              <Upload className="size-4" />
              <span className="hidden sm:inline">Import</span>
              <input
                type="file"
                accept="application/json,.json"
                className="sr-only"
                aria-label="Import agent from JSON"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void importFile(file);
                }}
              />
            </label>
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              New agent
            </Button>
          </>
        }
      />

      {isError && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}

      {isPending && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <Card key={i} className="space-y-4 p-5">
              <div className="flex gap-3">
                <Skeleton className="size-11 rounded-xl" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-1/3" />
                </div>
              </div>
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
            </Card>
          ))}
        </div>
      )}

      {agents && agents.length === 0 && (
        <EmptyState
          icon={<Bot />}
          title="Create your first agent"
          description="An agent combines a model, instructions, reusable skills and the tools it is allowed to use."
          action={
            <LinkButton to="/agents/new" variant="primary" icon={<Plus className="size-4" />
              }>
                New agent
            </LinkButton>
          }
        />
      )}

      {agents && agents.length > 0 && (
        <>
          {agents.length > 3 && (
            <div className="relative mb-5 max-w-sm">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
              <Input
                aria-label="Search agents"
                placeholder="Search agents…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-9"
              />
            </div>
          )}
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Agents">
            {filtered.map((agent) => (
              <li key={agent.id}>
                <Card className="group relative flex h-full flex-col p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-500/40 hover:shadow-pop">
                  <div className="flex items-center gap-3">
                    <AgentAvatar name={agent.name} />
                    <div className="min-w-0">
                      <h2 className="truncate font-semibold tracking-tight">
                        {/* Stretched link: the whole card opens the editor. */}
                        <Link
                          to={`/agents/${agent.id}`}
                          className="after:absolute after:inset-0 after:rounded-2xl focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-brand-500"
                        >
                          {agent.name}
                        </Link>
                      </h2>
                      <p className="text-xs text-subtle">Updated {relativeTime(agent.updated_at)}</p>
                    </div>
                  </div>
                  <p className="mt-4 line-clamp-2 min-h-10 flex-1 text-sm text-muted">
                    {agent.description || "No description."}
                  </p>
                  <div className="mt-4 flex items-center gap-2 border-t border-line pt-3 text-xs text-muted">
                    <Cpu className="size-3.5 shrink-0 text-subtle" />
                    <span className="min-w-0 truncate font-mono">{agent.model}</span>
                    <LinkButton
                      to={`/agents/${agent.id}/chat`}
                      size="sm"
                      variant="primary"
                      icon={<MessageSquare className="size-3.5" />}
                      className="relative z-10 ml-auto"
                      aria-label={`Chat with ${agent.name}`}
                    >
                      Chat
                    </LinkButton>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
          {filtered.length === 0 && (
            <p className="py-10 text-center text-sm text-muted">No agents match “{query}”.</p>
          )}
        </>
      )}
      {creating && <NewAgentDialog onClose={() => setCreating(false)} />}
    </>
  );
}
