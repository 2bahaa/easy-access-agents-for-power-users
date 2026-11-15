import { ArrowRight, BookOpen, Bot, Cpu, MessageSquare, Plus, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { useAgents, useAllConversations, useHealth, useModels, useSkills, useTools } from "../../api/queries";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { LinkButton } from "../../components/ui/LinkButton";
import { EmptyState, Skeleton } from "../../components/ui/States";
import { PageHeader } from "../../layout/PageHeader";
import { relativeTime } from "../../lib/format";

/**
 * Workspace overview. Every number comes from the API; a metric whose source is unavailable
 * shows "—" with an explanation instead of a made-up value.
 */
export function OverviewPage() {
  const agents = useAgents();
  const skills = useSkills();
  const tools = useTools();
  const conversations = useAllConversations();
  const health = useHealth();
  const models = useModels("ollama");

  const agentName = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
  const toolModels = models.data?.filter((m) => m.supports_tools).length;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Your agents, recent activity and the health of the services they depend on."
        actions={
          <LinkButton to="/agents/new" variant="primary" icon={<Plus className="size-4" />}>
            New agent
          </LinkButton>
        }
      />

      <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Agents" icon={<Bot />} value={agents.data?.length} loading={agents.isPending} error={agents.isError} to="/agents" />
        <Metric label="Skills" icon={<BookOpen />} value={skills.data?.length} loading={skills.isPending} error={skills.isError} to="/skills" />
        <Metric label="Tools" icon={<Wrench />} value={tools.data?.length} loading={tools.isPending} error={tools.isError} to="/tools" />
        <Metric
          label="Conversations"
          icon={<MessageSquare />}
          value={conversations.data?.length}
          loading={conversations.isPending}
          error={conversations.isError}
        />
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <header className="flex items-center justify-between border-b border-line px-5 py-4">
            <h2 className="text-[15px] font-semibold tracking-tight">Recent conversations</h2>
          </header>
          {conversations.isPending ? (
            <ul className="divide-y divide-line" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <li key={i} className="flex items-center gap-3 px-5 py-3.5">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="ml-auto h-3 w-16" />
                </li>
              ))}
            </ul>
          ) : conversations.isError ? (
            <p className="px-5 py-8 text-sm text-muted">Conversations are unavailable — the API could not be reached.</p>
          ) : conversations.data.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<MessageSquare />}
                title="No conversations yet"
                description="Open an agent and start chatting — conversations appear here."
              />
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {conversations.data.slice(0, 6).map((c) => (
                <li key={c.id}>
                  <Link
                    to={`/agents/${c.agent_id}/chat/${c.id}`}
                    className="group flex items-center gap-3 px-5 py-3 transition-colors hover:bg-surface-2/60"
                  >
                    <MessageSquare className="size-4 shrink-0 text-subtle" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{c.title || "Untitled conversation"}</span>
                      <span className="block truncate text-xs text-muted">{agentName.get(c.agent_id) ?? "Agent"}</span>
                    </span>
                    <span className="shrink-0 text-xs text-subtle">{relativeTime(c.updated_at)}</span>
                    <ArrowRight className="size-3.5 shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <header className="border-b border-line px-5 py-4">
            <h2 className="text-[15px] font-semibold tracking-tight">Services &amp; models</h2>
          </header>
          <ul className="space-y-3 px-5 py-4 text-sm">
            <ServiceRow label="API" state={health.isPending ? "pending" : health.isError ? "error" : "ok"} />
            <ServiceRow label="Database" state={health.data?.database ?? (health.isError ? "error" : "pending")} />
            <ServiceRow label="Ollama" state={health.data?.ollama ?? (health.isError ? "error" : "pending")} />
          </ul>
          <div className="border-t border-line px-5 py-4">
            <p className="flex items-center gap-2 text-sm font-medium">
              <Cpu className="size-4 text-subtle" /> Local models
            </p>
            {models.isPending ? (
              <Skeleton className="mt-2 h-4 w-32" />
            ) : models.isError ? (
              <p className="mt-1 text-sm text-muted">Model list unavailable — is Ollama running?</p>
            ) : (
              <p className="mt-1 text-sm text-muted">
                {models.data.length} installed · {toolModels} support tools
              </p>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

function Metric({
  label,
  icon,
  value,
  loading,
  error,
  to,
}: {
  label: string;
  icon: ReactNode;
  value: number | undefined;
  loading: boolean;
  error: boolean;
  to?: string;
}) {
  const body = (
    <Card className="h-full p-4 transition-colors hover:border-line-strong">
      <p className="flex items-center gap-2 text-xs font-medium text-muted [&_svg]:size-3.5">
        {icon}
        {label}
      </p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-12" />
      ) : (
        <p className="mt-1.5 text-2xl font-semibold tracking-tight tabular-nums" title={error ? "Unavailable" : undefined}>
          {error || value === undefined ? "—" : value}
        </p>
      )}
    </Card>
  );
  return to ? (
    <Link to={to} aria-label={`${label}: ${loading ? "loading" : error ? "unavailable" : value}`}>
      {body}
    </Link>
  ) : (
    <div aria-label={`${label}: ${loading ? "loading" : error ? "unavailable" : value}`}>{body}</div>
  );
}

function ServiceRow({ label, state }: { label: string; state: string }) {
  return (
    <li className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      {state === "ok" ? (
        <Badge tone="success">Online</Badge>
      ) : state === "error" ? (
        <Badge tone="danger">Offline</Badge>
      ) : (
        <Badge>Checking…</Badge>
      )}
    </li>
  );
}
