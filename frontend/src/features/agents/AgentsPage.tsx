import { ArrowUpRight, Bot, Cpu, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { errorMessage } from "../../api/client";
import { useAgents } from "../../api/queries";
import { LinkButton } from "../../components/ui/LinkButton";
import { Card } from "../../components/ui/Card";
import { Input } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { PageHeader } from "../../layout/PageHeader";
import { relativeTime } from "../../lib/format";
import { AgentAvatar } from "./AgentAvatar";

export function AgentsPage() {
  const { data: agents, isPending, isError, error, refetch } = useAgents();
  const [query, setQuery] = useState("");
  const filtered = (agents ?? []).filter((a) =>
    `${a.name} ${a.description} ${a.model}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <>
      <PageHeader
        title="Agents"
        description="Create agents, give them skills and tools, and choose the model they run on."
        actions={
          <LinkButton to="/agents/new" variant="primary" icon={<Plus className="size-4" />
              }>
              New agent
            </LinkButton>
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
                <Link
                  to={`/agents/${agent.id}`}
                  className="group block h-full rounded-2xl focus-visible:outline-offset-4"
                >
                  <Card className="relative flex h-full flex-col p-5 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:border-brand-500/40 group-hover:shadow-pop">
                    <ArrowUpRight className="absolute top-4 right-4 size-4 text-subtle opacity-0 transition-opacity group-hover:opacity-100" />
                    <div className="flex items-center gap-3">
                      <AgentAvatar name={agent.name} />
                      <div className="min-w-0">
                        <h2 className="truncate font-semibold tracking-tight">{agent.name}</h2>
                        <p className="text-xs text-subtle">
                          Updated {relativeTime(agent.updated_at)}
                        </p>
                      </div>
                    </div>
                    <p className="mt-4 line-clamp-2 min-h-10 flex-1 text-sm text-muted">
                      {agent.description || "No description."}
                    </p>
                    <div className="mt-4 flex items-center gap-2 border-t border-line pt-3 text-xs text-muted">
                      <Cpu className="size-3.5 text-subtle" />
                      <span className="truncate font-mono">{agent.model}</span>
                      <span className="ml-auto rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] capitalize">
                        {agent.provider}
                      </span>
                    </div>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
          {filtered.length === 0 && (
            <p className="py-10 text-center text-sm text-muted">No agents match “{query}”.</p>
          )}
        </>
      )}
    </>
  );
}
