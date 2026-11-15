import { ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { errorMessage } from "../../api/client";
import {
  useAgents,
  useApprovalPolicies,
  useApprovals,
  useCreateApprovalPolicy,
  useDecideApproval,
  useDeleteApprovalPolicy,
} from "../../api/queries";
import { ApprovalCard } from "../../components/ApprovalCard";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Field, Input, Select } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { cn } from "../../lib/cn";
import { relativeTime } from "../../lib/format";
import { prettyToolName } from "../../lib/tools";
import { roleAtLeast, useAuth } from "../auth/auth-context";

type Tab = "pending" | "history" | "policies";

export function ApprovalsPage() {
  const { role } = useAuth();
  const [tab, setTab] = useState<Tab>("pending");
  const tabs: Array<{ id: Tab; label: string; show: boolean }> = [
    { id: "pending", label: "Pending", show: true },
    { id: "history", label: "History", show: true },
    { id: "policies", label: "Policies", show: roleAtLeast(role, "admin") },
  ];
  return (
    <>
      <PageHeader
        title="Approvals"
        description="Tool calls held for a human decision. The model can never approve its own actions."
      />
      <div role="tablist" aria-label="Approval sections" className="mb-6 flex gap-1 border-b border-line">
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2.5 text-sm font-medium",
                tab === t.id ? "border-brand-500 text-fg" : "border-transparent text-muted hover:text-fg",
              )}
            >
              {t.label}
            </button>
          ))}
      </div>
      {tab === "pending" && <Pending canDecide={roleAtLeast(role, "editor")} />}
      {tab === "history" && <History />}
      {tab === "policies" && <Policies />}
    </>
  );
}

function Pending({ canDecide }: { canDecide: boolean }) {
  const approvals = useApprovals({ status: "pending" });
  const agents = useAgents();
  const decide = useDecideApproval();
  const toast = useToast();
  const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
  if (approvals.isPending) return <Skeleton className="h-32 rounded-2xl" />;
  if (approvals.isError) return <ErrorState message={errorMessage(approvals.error)} onRetry={() => void approvals.refetch()} />;
  if (approvals.data.length === 0)
    return <EmptyState icon={<ShieldCheck />} title="Nothing to review" description="Held tool calls appear here." />;
  return (
    <div className="space-y-3">
      {approvals.data.map((a) => (
        <ApprovalCard
          key={a.id}
          approval={a}
          disabled={!canDecide}
          busy={decide.isPending && decide.variables?.id === a.id}
          context={
            a.agent_id && a.conversation_id ? (
              <>
                {names.get(a.agent_id) ?? "Agent"} ·{" "}
                <Link className="text-brand-600 hover:underline dark:text-brand-400" to={`/agents/${a.agent_id}/chat/${a.conversation_id}`}>
                  open conversation
                </Link>{" "}
                · requested {relativeTime(a.created_at)}
              </>
            ) : (
              <>Workflow approval step · requested {relativeTime(a.created_at)}</>
            )
          }
          onDecide={(d) =>
            decide.mutate(
              { id: a.id, ...d },
              {
                onSuccess: (r) => toast.push({ title: d.approve ? "Approved" : "Rejected", description: r.continuation_run_id ? "The agent continues." : undefined }),
                onError: (error) => toast.push({ tone: "error", title: "Decision failed", description: errorMessage(error) }),
              },
            )
          }
        />
      ))}
    </div>
  );
}

const STATUS_TONE = { approved: "success", rejected: "danger", expired: "warning", cancelled: "neutral", pending: "brand" } as const;

function History() {
  const approvals = useApprovals({ status: "all" });
  if (approvals.isPending) return <Skeleton className="h-32 rounded-2xl" />;
  if (approvals.isError) return <ErrorState message={errorMessage(approvals.error)} />;
  return (
    <Card>
      <ul className="divide-y divide-line" aria-label="Approval history">
        {approvals.data.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
            <span className="font-medium">{prettyToolName(a.tool_name)}</span>
            <Badge tone={STATUS_TONE[a.status]}>{a.status}</Badge>
            {a.edited_args && <Badge>edited</Badge>}
            <span className="min-w-0 flex-1 truncate text-xs text-muted">{a.note}</span>
            <span className="text-xs text-subtle">{relativeTime(a.decided_at ?? a.created_at)}</span>
          </li>
        ))}
        {approvals.data.length === 0 && <li className="px-5 py-4 text-sm text-muted">No approvals yet.</li>}
      </ul>
    </Card>
  );
}

function Policies() {
  const policies = useApprovalPolicies();
  const agents = useAgents();
  const create = useCreateApprovalPolicy();
  const remove = useDeleteApprovalPolicy();
  const toast = useToast();
  const [pattern, setPattern] = useState("");
  const [agentId, setAgentId] = useState("");
  const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { pattern, agentId: agentId || null },
      {
        onSuccess: () => setPattern(""),
        onError: (error) => toast.push({ tone: "error", title: "Could not add policy", description: errorMessage(error) }),
      },
    );
  };

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end" aria-label="Add approval policy">
          <Field label="Tool pattern" hint="Glob, e.g. http__* or mcp__github__*" className="flex-1">
            {(p) => <Input {...p} value={pattern} onChange={(e) => setPattern(e.target.value)} />}
          </Field>
          <Field label="Applies to" className="sm:w-56">
            {(p) => (
              <Select {...p} value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="">All agents</option>
                {(agents.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!pattern}>
            Add policy
          </Button>
        </form>
      </Card>
      <Card>
        <ul className="divide-y divide-line" aria-label="Approval policies">
          {(policies.data ?? []).map((p) => (
            <li key={p.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <code className="font-mono">{p.tool_pattern}</code>
              <span className="flex-1 text-xs text-muted">{p.agent_id ? names.get(p.agent_id) ?? "one agent" : "all agents"}</span>
              <Button size="sm" variant="ghost" aria-label={`Delete policy ${p.tool_pattern}`} icon={<Trash2 className="size-4" />} onClick={() => remove.mutate(p.id)} />
            </li>
          ))}
          {policies.data?.length === 0 && <li className="px-5 py-4 text-sm text-muted">No workspace policies. Per-agent approval is set on each tool in the agent editor.</li>}
        </ul>
      </Card>
    </div>
  );
}
