import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";

import type { AgentEvent } from "../api/events";
import type { WorkflowNodeType, WorkflowSpec } from "../api/types";

export type NodeStatus = "idle" | "running" | "completed" | "failed" | "paused";

export interface WfNodeData extends Record<string, unknown> {
  nodeType: WorkflowNodeType;
  label: string;
  config: Record<string, unknown>;
  retries?: number;
  onError?: "fail" | "continue";
  status?: NodeStatus;
  output?: string;
  problem?: string;
}

export type WfNode = Node<WfNodeData, "wf">;

interface NodeMeta {
  title: string;
  description: string;
  /** Tailwind classes for the node accent. */
  accent: string;
  defaultConfig: () => Record<string, unknown>;
}

export const NODE_META: Record<WorkflowNodeType, NodeMeta> = {
  start: { title: "Start", description: "Workflow inputs", accent: "border-success/60 bg-success/5", defaultConfig: () => ({ inputs: [{ name: "text", description: "" }] }) },
  end: { title: "End", description: "Workflow result", accent: "border-success/60 bg-success/5", defaultConfig: () => ({ output: "" }) },
  agent: { title: "Agent", description: "Run one of your agents", accent: "border-brand-500/60 bg-brand-500/5", defaultConfig: () => ({ agent_id: "", prompt: "{{ input.text }}", use_draft: false }) },
  llm: { title: "LLM", description: "A single model call", accent: "border-brand-500/60 bg-brand-500/5", defaultConfig: () => ({ provider: "ollama", model: "qwen3:4b", system: "", prompt: "{{ input.text }}" }) },
  tool: { title: "Tool", description: "Call a tool", accent: "border-accent-500/60 bg-accent-500/5", defaultConfig: () => ({ tool: "calculator", args: { expression: "1+1" }, config: {} }) },
  knowledge: { title: "Knowledge", description: "Search collections", accent: "border-info/60 bg-info/5", defaultConfig: () => ({ collection_ids: [], query: "{{ input.text }}", top_k: 5 }) },
  memory: { title: "Memory", description: "Save or recall agent memory", accent: "border-info/60 bg-info/5", defaultConfig: () => ({ agent_id: "", action: "search", text: "{{ input.text }}" }) },
  condition: { title: "Condition", description: "Branch on an expression", accent: "border-warning/60 bg-warning/5", defaultConfig: () => ({ expression: 'contains(input_text, "yes")' }) },
  router: { title: "Router", description: "LLM picks a branch", accent: "border-warning/60 bg-warning/5", defaultConfig: () => ({ provider: "ollama", model: "qwen3:4b", routes: ["a", "b"], instructions: "", input: "{{ input.text }}" }) },
  parallel: { title: "Parallel", description: "Run branches at the same time", accent: "border-line-strong bg-surface-2", defaultConfig: () => ({}) },
  approval: { title: "Approval", description: "Wait for a human decision", accent: "border-danger/50 bg-danger/5", defaultConfig: () => ({ message: "Continue?" }) },
  supervisor: {
    title: "Team",
    description: "A supervisor delegates to member agents",
    accent: "border-accent-500/60 bg-accent-500/5",
    defaultConfig: () => ({ provider: "ollama", model: "qwen3:4b", instructions: "", task: "{{ input.text }}", members: [], max_delegations: 4, share_task_with_members: false }),
  },
};

export const PALETTE: WorkflowNodeType[] = ["start", "agent", "llm", "tool", "knowledge", "memory", "condition", "router", "parallel", "approval", "supervisor", "end"];

/** Output handles of a node: branch names, or a single unnamed handle. */
export function outputHandles(type: WorkflowNodeType, config: Record<string, unknown>): string[] {
  if (type === "end") return [];
  if (type === "condition") return ["true", "false"];
  if (type === "approval") return ["approved", "rejected"];
  if (type === "router") return ((config.routes as string[] | undefined) ?? []).filter(Boolean);
  return ["out"];
}

export function specToFlow(spec: WorkflowSpec): { nodes: WfNode[]; edges: Edge[] } {
  const nodes: WfNode[] = spec.nodes.map((n) => ({
    id: n.id,
    type: "wf",
    position: n.position ?? { x: 0, y: 0 },
    data: { nodeType: n.type, label: n.label ?? "", config: n.config ?? {}, retries: n.retries ?? 0, onError: n.on_error ?? "fail" },
  }));
  const edges: Edge[] = spec.edges.map((e, i) => ({
    id: `e${i}-${e.source}-${e.target}-${e.source_handle ?? "out"}`,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_handle ?? "out",
    label: e.source_handle ?? undefined,
  }));
  return { nodes, edges };
}

export function flowToSpec(nodes: WfNode[], edges: Edge[]): WorkflowSpec {
  return {
    schema_version: 1,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      label: n.data.label,
      config: n.data.config,
      ...(n.data.retries ? { retries: n.data.retries } : {}),
      ...(n.data.onError === "continue" ? { on_error: "continue" as const } : {}),
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    })),
    edges: edges.map((e) => ({
      source: e.source,
      target: e.target,
      source_handle: e.sourceHandle && e.sourceHandle !== "out" ? e.sourceHandle : null,
    })),
  };
}

/** A readable unique id for a new node (ids are referenced in templates: {{ id }}). */
export function nextNodeId(type: WorkflowNodeType, existing: Iterable<string>): string {
  const taken = new Set(existing);
  if (!taken.has(type) && type !== "start") return type;
  for (let i = 2; ; i++) {
    const id = `${type}_${i}`;
    if (!taken.has(id)) return id;
  }
}

export function autoLayout(nodes: WfNode[], edges: Edge[]): WfNode[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(n.id, { width: 220, height: 90 });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    return p ? { ...n, position: { x: p.x - 110, y: p.y - 45 } } : n;
  });
}

export interface RunView {
  status: "idle" | "running" | "completed" | "failed" | "cancelled" | "waiting_approval";
  nodes: Record<string, { status: NodeStatus; output?: string; error?: string; ms?: number }>;
  log: Array<{ seq: number; text: string; tone: "info" | "success" | "error" | "warning" }>;
  output: string | null;
}

export const initialRunView: RunView = { status: "idle", nodes: {}, log: [], output: null };

/** Reduce a workflow run's events into node statuses and a readable log. */
export function reduceRunEvent(view: RunView, e: AgentEvent): RunView {
  const log = (text: string, tone: RunView["log"][number]["tone"] = "info") => [...view.log, { seq: e.seq, text, tone }];
  switch (e.type) {
    case "run.started":
      return { ...initialRunView, status: "running", log: [{ seq: e.seq, text: "Run started", tone: "info" }] };
    case "node.started":
      return { ...view, nodes: { ...view.nodes, [e.node_id]: { status: "running" } }, log: log(`▶ ${e.label || e.node_id}`) };
    case "node.completed":
      return {
        ...view,
        nodes: { ...view.nodes, [e.node_id]: { status: "completed", output: e.output, ms: e.duration_ms } },
        log: log(`✓ ${e.node_id} (${e.duration_ms} ms)`, "success"),
      };
    case "node.failed":
      if (e.will_retry) return { ...view, log: log(`↻ ${e.node_id}: ${e.error} — retrying`, "warning") };
      if (e.continued) return { ...view, nodes: { ...view.nodes, [e.node_id]: { status: "completed", error: e.error } }, log: log(`⚠ ${e.node_id}: ${e.error} — continuing`, "warning") };
      return { ...view, nodes: { ...view.nodes, [e.node_id]: { status: "failed", error: e.error } }, log: log(`✗ ${e.node_id}: ${e.error}`, "error") };
    case "agent.delegated":
      return { ...view, log: log(`→ ${e.node_id} delegated to ${e.member}${e.reason ? ` (${e.reason})` : ""}: ${e.task}`) };
    case "agent.result":
      return { ...view, log: log(`${e.ok ? "←" : "✗"} ${e.member} answered in ${(e.duration_ms / 1000).toFixed(1)} s: ${e.output}`, e.ok ? undefined : "error") };
    case "approval.requested":
      return { ...view, nodes: { ...view.nodes, [e.call_id]: { status: "paused" } }, log: log(`⏸ ${e.call_id} waits for approval`, "warning") };
    case "run.waiting_approval":
      return { ...view, status: "waiting_approval", log: log("Paused — approve it on the Approvals page", "warning") };
    case "run.completed":
      return { ...view, status: "completed", output: e.output ?? "", log: log(`Completed in ${(e.duration_ms / 1000).toFixed(1)} s`, "success") };
    case "run.failed":
      return { ...view, status: "failed", log: log(`Failed: ${e.message}`, "error") };
    case "run.cancelled":
      return { ...view, status: "cancelled", log: log("Cancelled", "warning") };
    default:
      return view;
  }
}
