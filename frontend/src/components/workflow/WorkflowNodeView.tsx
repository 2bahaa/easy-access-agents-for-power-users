import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Bot,
  Brain,
  CheckCircle2,
  Cpu,
  Database,
  Flag,
  GitBranch,
  Loader2,
  PauseCircle,
  Play,
  Route,
  ShieldQuestion,
  Split,
  Wrench,
  XCircle,
} from "lucide-react";
import type { ComponentType } from "react";

import type { WorkflowNodeType } from "../../api/types";
import { cn } from "../../lib/cn";
import { NODE_META, outputHandles, type WfNode } from "../../lib/workflowGraph";

const ICONS: Record<WorkflowNodeType, ComponentType<{ className?: string }>> = {
  start: Play,
  end: Flag,
  agent: Bot,
  llm: Cpu,
  tool: Wrench,
  knowledge: Database,
  memory: Brain,
  condition: GitBranch,
  router: Route,
  parallel: Split,
  approval: ShieldQuestion,
};

const STATUS_RING = {
  idle: "",
  running: "ring-2 ring-brand-500 ring-offset-2 ring-offset-canvas animate-pulse",
  completed: "ring-2 ring-success ring-offset-2 ring-offset-canvas",
  failed: "ring-2 ring-danger ring-offset-2 ring-offset-canvas",
  paused: "ring-2 ring-warning ring-offset-2 ring-offset-canvas",
} as const;

function StatusIcon({ status }: { status?: string }) {
  if (status === "running") return <Loader2 className="size-3.5 animate-spin text-brand-500" aria-label="running" />;
  if (status === "completed") return <CheckCircle2 className="size-3.5 text-success" aria-label="completed" />;
  if (status === "failed") return <XCircle className="size-3.5 text-danger" aria-label="failed" />;
  if (status === "paused") return <PauseCircle className="size-3.5 text-warning" aria-label="waiting for approval" />;
  return null;
}

/** Canvas node: title, id (used in {{ templates }}), live status and one handle per branch. */
export function WorkflowNodeView({ id, data, selected }: NodeProps<WfNode>) {
  const meta = NODE_META[data.nodeType];
  const Icon = ICONS[data.nodeType];
  const handles = outputHandles(data.nodeType, data.config);
  return (
    <div
      data-testid={`wf-node-${id}`}
      className={cn(
        "w-[220px] rounded-xl border-2 bg-surface px-3 py-2.5 text-left shadow-card transition-shadow",
        meta.accent,
        selected && "shadow-pop outline-2 outline-offset-2 outline-brand-500",
        STATUS_RING[data.status ?? "idle"],
        data.problem && "border-danger",
      )}
    >
      {data.nodeType !== "start" && <Handle type="target" position={Position.Left} className="!size-3 !bg-line-strong" />}
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-muted" />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{data.label || meta.title}</span>
        <StatusIcon status={data.status} />
      </div>
      <p className="mt-0.5 truncate font-mono text-[10px] text-subtle">{id}</p>
      {data.problem && <p className="mt-1 text-[11px] leading-tight text-danger">{data.problem}</p>}
      {data.output && <p className="mt-1 line-clamp-2 text-[11px] text-muted">{data.output}</p>}
      {handles.length === 1 && handles[0] === "out" && (
        <Handle id="out" type="source" position={Position.Right} className="!size-3 !bg-brand-500" />
      )}
      {handles.length > 0 && handles[0] !== "out" && (
        <div className="mt-2 flex flex-col items-end gap-1">
          {handles.map((h) => (
            <div key={h} className="relative pr-3 text-[10px] font-medium text-muted">
              {h}
              <Handle id={h} type="source" position={Position.Right} className="!right-[-14px] !size-2.5 !bg-warning" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
