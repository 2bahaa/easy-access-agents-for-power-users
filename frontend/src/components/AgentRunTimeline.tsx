import { AlertTriangle, Ban, Brain, CheckCircle2, ChevronRight, CircleDot, Loader2, MessageSquare, PauseCircle, Play, ShieldQuestion, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { failureText, type RunState, type TimelineItem } from "../lib/runReducer";
import { prettyToolName } from "../lib/tools";
import { ToolIcon } from "./ToolIcon";
import { Badge } from "./ui/Badge";
import { Skeleton } from "./ui/States";

export interface AgentRunTimelineProps {
  items: TimelineItem[];
  status: RunState["status"];
  loading?: boolean;
  /** Text shown when there is no run to display. */
  emptyText?: string;
}

/** Step-by-step view of a run: start, reasoning, tool calls with args/results, messages, outcome. */
export function AgentRunTimeline({ items, status, loading, emptyText }: AgentRunTimelineProps) {
  if (loading) {
    return (
      <div className="space-y-3 p-1" aria-busy="true">
        <Skeleton className="h-10" />
        <Skeleton className="h-20" />
        <Skeleton className="h-10" />
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong p-5 text-center text-sm text-muted">
        {status === "streaming" ? "Waiting for the first event…" : (emptyText ?? "No run selected.")}
      </p>
    );
  }
  return (
    <ol aria-label="Run timeline" className="relative space-y-1">
      {items.map((item, index) => (
        <TimelineRow key={`${item.kind}-${item.seq}`} item={item} last={index === items.length - 1} />
      ))}
      {status === "streaming" && (
        <li className="flex items-center gap-3 py-1.5 pl-1 text-xs text-muted">
          <Loader2 className="size-4 animate-spin text-brand-500" /> Working…
        </li>
      )}
    </ol>
  );
}

function TimelineRow({ item, last }: { item: TimelineItem; last: boolean }) {
  const icon = rowIcon(item);
  return (
    <li className="relative flex gap-3">
      {!last && <span aria-hidden="true" className="absolute top-8 bottom-0 left-[15px] w-px bg-line" />}
      <span
        className={cn(
          "relative z-10 mt-1 grid size-8 shrink-0 place-items-center rounded-full ring-4 ring-surface [&_svg]:size-4",
          icon.className,
        )}
      >
        {icon.node}
      </span>
      <div className="min-w-0 flex-1 pt-1.5 pb-3">
        <RowBody item={item} />
      </div>
    </li>
  );
}

function rowIcon(item: TimelineItem): { node: ReactNode; className: string } {
  switch (item.kind) {
    case "started":
      return { node: <Play />, className: "bg-brand-500/10 text-brand-600 dark:text-brand-400" };
    case "reasoning":
      return { node: <Brain />, className: "bg-accent-500/10 text-purple-600 dark:text-purple-300" };
    case "message":
      return { node: <MessageSquare />, className: "bg-surface-2 text-muted" };
    case "tool":
      if (item.status === "running")
        return { node: <Loader2 className="animate-spin" />, className: "bg-brand-500/10 text-brand-600" };
      if (item.status === "failed") return { node: <XCircle />, className: "bg-red-500/10 text-red-500" };
      return { node: <ToolIcon name={item.tool} />, className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" };
    case "approval":
      return { node: <ShieldQuestion />, className: "bg-warning/10 text-warning" };
    case "end":
      if (item.status === "waiting_approval") return { node: <PauseCircle />, className: "bg-warning/10 text-warning" };
      if (item.status === "completed")
        return { node: <CheckCircle2 />, className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" };
      if (item.status === "cancelled") return { node: <Ban />, className: "bg-surface-2 text-muted" };
      return { node: <AlertTriangle />, className: "bg-red-500/10 text-red-500" };
    default:
      return { node: <CircleDot />, className: "bg-surface-2 text-muted" };
  }
}

function RowBody({ item }: { item: TimelineItem }) {
  switch (item.kind) {
    case "started":
      return (
        <p className="text-sm">
          <span className="font-medium">Run started</span>{" "}
          <span className="font-mono text-xs text-muted">{item.model}</span>
        </p>
      );
    case "reasoning":
      return (
        <Collapsible label="Reasoning" defaultOpen={false}>
          <p className="text-xs leading-relaxed whitespace-pre-wrap text-muted">{item.text}</p>
        </Collapsible>
      );
    case "message":
      return (
        <div>
          <p className="text-sm font-medium">Assistant message</p>
          <p className="mt-0.5 line-clamp-3 text-xs text-muted">{item.content}</p>
        </div>
      );
    case "tool":
      return (
        <div className="rounded-xl border border-line bg-surface-2/50 p-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{prettyToolName(item.tool)}</span>
            {item.status === "running" && <Badge tone="brand">running</Badge>}
            {item.status === "completed" && (
              <Badge tone="success">{item.durationMs !== undefined ? `${item.durationMs} ms` : "done"}</Badge>
            )}
            {item.status === "failed" && <Badge tone="danger">{item.errorKind ?? "failed"}</Badge>}
          </div>
          <Code label="Arguments">{JSON.stringify(item.args, null, 2)}</Code>
          {item.result !== undefined && <Code label="Result">{item.result}</Code>}
          {item.error && (
            <p className="mt-2 rounded-lg bg-red-500/10 px-2.5 py-1.5 text-xs text-red-700 dark:text-red-300">
              {item.error}
            </p>
          )}
        </div>
      );
    case "approval":
      return (
        <div className="rounded-xl border border-warning/30 bg-warning/5 p-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{prettyToolName(item.tool)}</span>
            <Badge tone="warning">needs approval</Badge>
          </div>
          <Code label="Arguments">{JSON.stringify(item.args, null, 2)}</Code>
        </div>
      );
    case "end":
      if (item.status === "waiting_approval")
        return <p className="text-sm font-medium text-warning">Paused — waiting for a human decision</p>;
      if (item.status === "completed") {
        return (
          <div className="text-sm">
            <p className="font-medium text-emerald-700 dark:text-emerald-400">Completed</p>
            <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted">
              {item.durationMs !== undefined && <span>{(item.durationMs / 1000).toFixed(1)} s</span>}
              {item.toolCallCount !== undefined && (
                <span>
                  {item.toolCallCount} tool {item.toolCallCount === 1 ? "call" : "calls"}
                </span>
              )}
              {item.usage?.total_tokens !== undefined && <span>{item.usage.total_tokens} tokens</span>}
            </p>
          </div>
        );
      }
      if (item.status === "cancelled") return <p className="text-sm font-medium text-muted">Cancelled</p>;
      return (
        <div className="text-sm">
          <p className="font-medium text-red-600 dark:text-red-400">Failed</p>
          <p className="mt-0.5 text-xs text-muted">{failureText(item.code, item.message)}</p>
        </div>
      );
  }
}

function Code({ label, children }: { label: string; children: string }) {
  return (
    <div className="mt-2">
      <p className="mb-1 text-[10px] font-semibold tracking-wider text-subtle uppercase">{label}</p>
      <pre className="scrollbar-thin max-h-40 overflow-auto rounded-lg bg-surface px-2.5 py-2 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-words ring-1 ring-line">
        {children}
      </pre>
    </div>
  );
}

function Collapsible({
  label,
  defaultOpen,
  children,
}: {
  label: string;
  defaultOpen: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-sm font-medium hover:text-brand-600"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        {label}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}
