import { History, RotateCcw, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { AgentEvent } from "../../api/events";
import { useAnalytics, useRunEvents, useRuns } from "../../api/queries";
import type { RunEventRecord, RunListItem } from "../../api/types";
import { AgentRunTimeline } from "../../components/AgentRunTimeline";
import { UsageChart } from "../../components/UsageChart";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Select } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { cn } from "../../lib/cn";
import { relativeTime } from "../../lib/format";
import { replayRunEvents } from "../../lib/runReducer";
import { initialRunView, reduceRunEvent } from "../../lib/workflowGraph";
import { roleAtLeast, useAuth } from "../auth/auth-context";

const PAGE = 25;
const ACTIVE = new Set(["queued", "running", "resumed"]);

function statusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "waiting_approval" || ACTIVE.has(status))
    return "warning" as const;
  if (status === "cancelled") return "neutral" as const;
  return "danger" as const;
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function durationOf(run: RunListItem): number | null {
  return run.finished_at
    ? new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
    : null;
}

/** Execution history with real usage analytics, filters and per-run timelines. */
export function RunsPage() {
  const [days, setDays] = useState(7);
  const [kind, setKind] = useState<"" | "agent" | "workflow">("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<RunListItem | null>(null);
  const analytics = useAnalytics(days);
  const runs = useRuns({
    kind: kind || undefined,
    status: status || undefined,
    limit: PAGE,
    offset,
  });

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every agent and workflow execution in this workspace, with usage measured from recorded runs."
      />

      <section aria-label="Usage" className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-[15px] font-semibold tracking-tight">Usage</h2>
          <Select
            aria-label="Time window"
            className="ml-auto h-8 w-36"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={1}>Last 24 hours</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
          </Select>
        </div>
        <AnalyticsPanel query={analytics} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card>
          <header className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
            <h2 className="mr-auto text-[15px] font-semibold tracking-tight">
              History
            </h2>
            <Select
              aria-label="Filter by kind"
              className="h-8 w-32"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as typeof kind);
                setOffset(0);
              }}
            >
              <option value="">All kinds</option>
              <option value="agent">Agent</option>
              <option value="workflow">Workflow</option>
            </Select>
            <Select
              aria-label="Filter by status"
              className="h-8 w-40"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">All statuses</option>
              {[
                "completed",
                "failed",
                "running",
                "queued",
                "waiting_approval",
                "cancelled",
                "timeout",
                "limit_exceeded",
              ].map((s) => (
                <option key={s} value={s}>
                  {s.replace("_", " ")}
                </option>
              ))}
            </Select>
          </header>
          {runs.isPending ? (
            <div className="space-y-2 p-5" aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : runs.isError ? (
            <div className="p-5">
              <ErrorState
                title="Could not load runs"
                message={errorMessage(runs.error)}
              />
            </div>
          ) : runs.data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<History />}
                title="No runs yet"
                description={
                  kind || status
                    ? "No runs match these filters."
                    : "Chat with an agent or run a workflow — executions appear here."
                }
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="px-5 py-2 font-medium">Run</th>
                      <th className="px-2 py-2 font-medium">Status</th>
                      <th className="px-2 py-2 font-medium">Duration</th>
                      <th className="px-2 py-2 font-medium">Tools</th>
                      <th className="px-2 py-2 font-medium">Tokens</th>
                      <th className="px-5 py-2 text-right font-medium">
                        Started
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {runs.data.items.map((r) => (
                      <tr
                        key={r.id}
                        className={cn(
                          "cursor-pointer hover:bg-surface-2/60",
                          selected?.id === r.id && "bg-surface-2",
                        )}
                        onClick={() => setSelected(r)}
                      >
                        <td className="px-5 py-2.5">
                          <button
                            type="button"
                            className="text-left font-medium hover:underline"
                            onClick={() => setSelected(r)}
                          >
                            {r.workflow_name ?? r.agent_name ?? "Deleted"}
                          </button>
                          <span className="ml-2 text-xs text-subtle">
                            {r.kind ?? "agent"}
                          </span>
                        </td>
                        <td className="px-2 py-2.5">
                          <Badge tone={statusTone(r.status)}>
                            {r.status.replace("_", " ")}
                          </Badge>
                        </td>
                        <td className="px-2 py-2.5 tabular-nums">
                          {formatDuration(durationOf(r))}
                        </td>
                        <td className="px-2 py-2.5 tabular-nums">
                          {r.tool_call_count}
                        </td>
                        <td className="px-2 py-2.5 tabular-nums">
                          {r.usage.total_tokens ?? "—"}
                        </td>
                        <td className="px-5 py-2.5 text-right text-xs text-muted">
                          {relativeTime(r.started_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <footer className="flex items-center gap-2 border-t border-line px-5 py-2 text-xs text-muted">
                {offset + 1}–{offset + runs.data.items.length} of{" "}
                {runs.data.total}
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={offset + PAGE >= runs.data.total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Next
                </Button>
              </footer>
            </>
          )}
        </Card>
        <RunDetail run={selected} onChanged={() => void runs.refetch()} />
      </div>
    </>
  );
}

function AnalyticsPanel({ query }: { query: ReturnType<typeof useAnalytics> }) {
  if (query.isPending) return <Skeleton className="h-40 rounded-2xl" />;
  if (query.isError)
    return (
      <p className="rounded-xl border border-line p-4 text-sm text-muted">
        Usage is unavailable — {errorMessage(query.error)}
      </p>
    );
  const s = query.data;
  const tokens = s.input_tokens + s.output_tokens;
  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Card className="p-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Runs" value={String(s.runs)} />
          <Stat
            label="Success rate"
            value={
              s.success_rate === null
                ? "—"
                : `${Math.round(s.success_rate * 100)}%`
            }
            hint="completed ÷ (completed + failed)"
          />
          <Stat
            label="Avg / p95 duration"
            value={`${formatDuration(s.avg_duration_ms)} / ${formatDuration(s.p95_duration_ms)}`}
          />
          <Stat
            label="Tokens (in / out)"
            value={
              tokens
                ? `${s.input_tokens.toLocaleString()} / ${s.output_tokens.toLocaleString()}`
                : "—"
            }
            hint={
              s.runs_without_usage
                ? `${s.runs_without_usage} run(s) had no usage reported by the provider`
                : "as reported by providers"
            }
          />
        </dl>
        <UsageChart className="mt-4" daily={s.daily} />
        <p className="mt-1 flex justify-between text-[11px] text-subtle">
          <span>{s.daily[0]?.date}</span>
          <span>{s.tool_calls} tool call(s)</span>
          <span>{s.daily.at(-1)?.date}</span>
        </p>
      </Card>
      <Card className="p-4 text-sm">
        <p className="mb-2 text-xs font-semibold tracking-wider text-subtle uppercase">
          Top agents
        </p>
        {s.top_agents.length === 0 ? (
          <p className="text-muted">No agent runs in this window.</p>
        ) : (
          <ul className="space-y-1">
            {s.top_agents.map((a) => (
              <li key={a.agent_id} className="flex justify-between gap-2">
                <Link
                  to={`/agents/${a.agent_id}`}
                  className="truncate hover:underline"
                >
                  {a.name}
                </Link>
                <span className="tabular-nums text-muted">
                  {a.runs}
                  {a.failed ? ` · ${a.failed} failed` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 mb-2 text-xs font-semibold tracking-wider text-subtle uppercase">
          Top tools
        </p>
        {s.top_tools.length === 0 ? (
          <p className="text-muted">No tool calls in this window.</p>
        ) : (
          <ul className="space-y-1" aria-label="Top tools">
            {s.top_tools.map((t) => (
              <li key={t.tool} className="flex justify-between gap-2">
                <span className="truncate font-mono text-xs">{t.tool}</span>
                <span className="tabular-nums text-muted">
                  {t.calls}
                  {t.failed ? ` · ${t.failed} failed` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div title={hint}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd
        className="mt-0.5 text-lg font-semibold tracking-tight tabular-nums"
        aria-label={`${label}: ${value}`}
      >
        {value}
      </dd>
    </div>
  );
}

function RunDetail({
  run,
  onChanged,
}: {
  run: RunListItem | null;
  onChanged: () => void;
}) {
  const toast = useToast();
  const { role } = useAuth();
  const active = !!run && ACTIVE.has(run.status);
  const events = useRunEvents(run?.id, !!run);
  const timeline = useMemo(
    () =>
      run && events.data && run.kind !== "workflow"
        ? replayRunEvents(run.id, events.data)
        : null,
    [run, events.data],
  );
  const workflowLog = useMemo(
    () =>
      run?.kind === "workflow" && events.data
        ? events.data
            .map(
              (e: RunEventRecord) =>
                ({
                  ...e.payload,
                  type: e.type,
                  seq: e.seq,
                }) as unknown as AgentEvent,
            )
            .reduce(reduceRunEvent, initialRunView).log
        : null,
    [run, events.data],
  );

  if (!run) {
    return (
      <Card className="p-5 text-sm text-muted">
        Select a run to see its timeline, errors and output.
      </Card>
    );
  }
  const rerun = async () => {
    try {
      await api.startWorkflowRun(run.workflow_id!, run.inputs ?? {});
      toast.push({ title: "Started a new run with the same inputs" });
      onChanged();
    } catch (error) {
      toast.push({
        tone: "error",
        title: "Could not start the run",
        description: errorMessage(error),
      });
    }
  };
  const cancel = async () => {
    await api.cancelRun(run.id).catch(() => undefined);
    toast.push({ title: "Cancellation requested" });
    onChanged();
  };
  return (
    <Card className="p-5" aria-label="Run details">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold tracking-tight">
          {run.workflow_name ?? run.agent_name ?? "Run"}
        </h2>
        <Badge tone={statusTone(run.status)}>
          {run.status.replace("_", " ")}
        </Badge>
        <div className="ml-auto flex gap-1.5">
          {active && roleAtLeast(role, "editor") && (
            <Button
              size="sm"
              variant="danger"
              icon={<Square className="size-3.5" />}
              onClick={() => void cancel()}
            >
              Cancel
            </Button>
          )}
          {run.kind === "workflow" &&
            run.workflow_id &&
            !active &&
            roleAtLeast(role, "editor") && (
              <Button
                size="sm"
                icon={<RotateCcw className="size-3.5" />}
                onClick={() => void rerun()}
              >
                Run again
              </Button>
            )}
        </div>
      </div>
      <p className="mb-3 font-mono text-[11px] text-subtle">{run.id}</p>
      {run.conversation_id && run.agent_id && (
        <Link
          className="mb-3 block text-sm text-brand-600 hover:underline"
          to={`/agents/${run.agent_id}/chat/${run.conversation_id}`}
        >
          Open conversation
        </Link>
      )}
      {run.error && (
        <p className="mb-3 rounded-lg bg-danger/10 p-2 text-xs text-danger">
          {run.error}
        </p>
      )}
      {run.output && (
        <pre
          aria-label="Run output"
          className="mb-3 max-h-40 overflow-auto rounded-lg bg-surface-2 p-2 text-xs whitespace-pre-wrap"
        >
          {run.output}
        </pre>
      )}
      {events.isError ? (
        <p className="text-sm text-muted">
          Timeline unavailable — {errorMessage(events.error)}
        </p>
      ) : workflowLog ? (
        <ol aria-label="Run log" className="space-y-0.5 font-mono text-[11px]">
          {workflowLog.map((l) => (
            <li
              key={l.seq}
              className={cn(
                l.tone === "error" && "text-danger",
                l.tone === "success" && "text-success",
                l.tone === "warning" && "text-warning",
              )}
            >
              {l.text}
            </li>
          ))}
        </ol>
      ) : (
        <AgentRunTimeline
          items={timeline?.items ?? []}
          status={timeline?.status ?? "idle"}
          loading={events.isPending}
          emptyText="No events recorded for this run."
        />
      )}
    </Card>
  );
}
