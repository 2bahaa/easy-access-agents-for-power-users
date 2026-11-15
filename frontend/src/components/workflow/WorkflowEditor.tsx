import "@xyflow/react/dist/style.css";

import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import { Copy, LayoutGrid, Redo2, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import type { SpecProblem, WorkflowNodeType, WorkflowSpec } from "../../api/types";
import { cn } from "../../lib/cn";
import {
  autoLayout,
  flowToSpec,
  NODE_META,
  nextNodeId,
  PALETTE,
  specToFlow,
  type RunView,
  type WfNode,
} from "../../lib/workflowGraph";
import { Button } from "../ui/Button";
import { NodeInspector, type WorkflowCatalogs } from "./NodeInspector";
import { WorkflowNodeView } from "./WorkflowNodeView";

const NODE_TYPES: NodeTypes = { wf: WorkflowNodeView };
const DND_TYPE = "application/x-eaa-workflow-node";
const HISTORY_LIMIT = 100;

export interface WorkflowEditorProps {
  /** Initial spec; changes are reported through onChange. */
  value: WorkflowSpec;
  onChange: (spec: WorkflowSpec) => void;
  catalogs: WorkflowCatalogs;
  /** Server validation problems (shown on the nodes). */
  problems?: SpecProblem[];
  /** Live or last run (node statuses and outputs). */
  run?: RunView | null;
  readOnly?: boolean;
}

/** Drag-and-drop workflow editor (React Flow). Prop-driven: no data fetching. */
export function WorkflowEditor(props: WorkflowEditorProps) {
  return (
    <ReactFlowProvider>
      <EditorInner {...props} />
    </ReactFlowProvider>
  );
}

function EditorInner({ value, onChange, catalogs, problems = [], run, readOnly }: WorkflowEditorProps) {
  const initial = useMemo(() => specToFlow(value), [value]);
  const [nodes, setNodes, onNodesChange] = useNodesState<WfNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const history = useRef<{ past: string[]; future: string[] }>({ past: [], future: [] });
  const clipboard = useRef<WfNode[]>([]);
  const flow = useReactFlow();

  // Report every structural change; keep an undo history of snapshots.
  const snapshot = useMemo(() => JSON.stringify(flowToSpec(nodes, edges)), [nodes, edges]);
  const last = useRef(snapshot);
  useEffect(() => {
    if (snapshot === last.current) return;
    history.current.past = [...history.current.past, last.current].slice(-HISTORY_LIMIT);
    history.current.future = [];
    last.current = snapshot;
    onChange(JSON.parse(snapshot) as WorkflowSpec);
  }, [snapshot, onChange]);

  const restore = (json: string) => {
    const { nodes: n, edges: e } = specToFlow(JSON.parse(json) as WorkflowSpec);
    last.current = json;
    setNodes(n);
    setEdges(e);
    onChange(JSON.parse(json) as WorkflowSpec);
  };
  const undo = () => {
    const prev = history.current.past.pop();
    if (prev === undefined) return;
    history.current.future.push(last.current);
    restore(prev);
  };
  const redo = () => {
    const next = history.current.future.pop();
    if (next === undefined) return;
    history.current.past.push(last.current);
    restore(next);
  };

  const addNode = useCallback(
    (type: WorkflowNodeType, position?: { x: number; y: number }) => {
      setNodes((current) => {
        const id = nextNodeId(type, current.map((n) => n.id));
        const center = position ?? { x: 120 + current.length * 30, y: 120 + current.length * 20 };
        setSelectedId(id);
        return [...current, { id, type: "wf", position: center, data: { nodeType: type, label: NODE_META[type].title, config: NODE_META[type].defaultConfig() } }];
      });
    },
    [setNodes],
  );

  const duplicate = (ids: string[]) => {
    const sources = nodes.filter((n) => ids.includes(n.id));
    if (sources.length === 0) return;
    setNodes((current) => {
      const taken = current.map((n) => n.id);
      const copies = sources.map((s) => {
        const id = nextNodeId(s.data.nodeType, taken);
        taken.push(id);
        return { ...s, id, selected: true, position: { x: s.position.x + 40, y: s.position.y + 40 }, data: { ...s.data, status: undefined, output: undefined } };
      });
      return [...current.map((n) => ({ ...n, selected: false })), ...copies];
    });
  };

  const deleteSelected = () => {
    const ids = new Set(nodes.filter((n) => n.selected || n.id === selectedId).map((n) => n.id));
    setNodes((c) => c.filter((n) => !ids.has(n.id)));
    setEdges((c) => c.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
    setSelectedId(null);
  };

  // Keyboard shortcuts on the canvas.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (readOnly || (e.target as HTMLElement).closest("input, textarea, select")) return;
    const mod = e.ctrlKey || e.metaKey;
    const selected = nodes.filter((n) => n.selected).map((n) => n.id);
    if (!mod) return;
    const key = e.key.toLowerCase();
    if (key === "z") {
      if (e.shiftKey) redo();
      else undo();
      e.preventDefault();
    } else if (key === "y") {
      redo();
      e.preventDefault();
    } else if (key === "c") {
      clipboard.current = nodes.filter((n) => n.selected);
    } else if (key === "v") {
      duplicate(clipboard.current.map((n) => n.id));
    } else if (key === "d") {
      duplicate(selected);
      e.preventDefault();
    }
  };

  const isValidConnection = (c: Connection | Edge) => {
    if (c.source === c.target) return false;
    const target = nodes.find((n) => n.id === c.target);
    const source = nodes.find((n) => n.id === c.source);
    return target?.data.nodeType !== "start" && source?.data.nodeType !== "end";
  };

  const onConnect = (c: Connection) =>
    setEdges((current) =>
      addEdge({ ...c, label: c.sourceHandle && c.sourceHandle !== "out" ? c.sourceHandle : undefined }, current),
    );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData(DND_TYPE) as WorkflowNodeType;
    if (!type || !(type in NODE_META)) return;
    addNode(type, flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  // Decorate nodes with server problems and live run state.
  const problemsBy = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const p of problems) if (p.node_id) map.set(p.node_id, [...(map.get(p.node_id) ?? []), p.message]);
    return map;
  }, [problems]);
  const decorated = useMemo(
    () =>
      nodes.map((n) => {
        const r = run?.nodes[n.id];
        return { ...n, data: { ...n.data, status: r?.status, output: r?.output ?? r?.error, problem: problemsBy.get(n.id)?.[0] } };
      }),
    [nodes, run, problemsBy],
  );
  const animatedEdges = useMemo(
    () =>
      edges.map((e) => {
        const done = run?.nodes[e.source]?.status === "completed" && run?.nodes[e.target];
        return { ...e, animated: !!done, style: done ? { stroke: "var(--color-success)", strokeWidth: 2 } : undefined };
      }),
    [edges, run],
  );

  const selected = nodes.find((n) => n.id === selectedId);
  const globalProblems = problems.filter((p) => !p.node_id);

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[180px_minmax(0,1fr)_320px]" onKeyDown={onKeyDown}>
      <aside aria-label="Node palette" className="hidden border-r border-line bg-surface p-3 lg:block">
        <p className="mb-2 text-[11px] font-semibold tracking-wider text-subtle uppercase">Drag onto the canvas</p>
        <ul className="space-y-1.5">
          {PALETTE.map((type) => (
            <li key={type}>
              <button
                type="button"
                draggable={!readOnly}
                disabled={readOnly}
                onDragStart={(e) => {
                  e.dataTransfer.setData(DND_TYPE, type);
                  e.dataTransfer.effectAllowed = "move";
                }}
                onClick={() => addNode(type)}
                aria-label={`Add ${NODE_META[type].title} node`}
                className={cn("w-full cursor-grab rounded-lg border-2 px-2.5 py-1.5 text-left text-xs font-medium active:cursor-grabbing", NODE_META[type].accent)}
              >
                {NODE_META[type].title}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div className="relative min-h-[420px]" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
        <div className="absolute top-3 left-3 z-10 flex gap-1 rounded-xl border border-line bg-surface/90 p-1 shadow-card backdrop-blur">
          <Button size="sm" variant="ghost" aria-label="Undo" title="Undo (Ctrl+Z)" icon={<Undo2 className="size-4" />} onClick={undo} disabled={readOnly} />
          <Button size="sm" variant="ghost" aria-label="Redo" title="Redo (Ctrl+Y)" icon={<Redo2 className="size-4" />} onClick={redo} disabled={readOnly} />
          <Button size="sm" variant="ghost" aria-label="Auto-layout" title="Auto-layout" icon={<LayoutGrid className="size-4" />} onClick={() => { setNodes((c) => autoLayout(c, edges)); window.requestAnimationFrame(() => void flow.fitView()); }} disabled={readOnly} />
          <Button size="sm" variant="ghost" aria-label="Duplicate selection" title="Duplicate (Ctrl+D)" icon={<Copy className="size-4" />} onClick={() => duplicate(nodes.filter((n) => n.selected || n.id === selectedId).map((n) => n.id))} disabled={readOnly} />
          <Button size="sm" variant="ghost" aria-label="Delete selection" title="Delete" icon={<Trash2 className="size-4" />} onClick={deleteSelected} disabled={readOnly} />
        </div>
        {globalProblems.length > 0 && (
          <ul role="alert" className="absolute right-3 bottom-3 z-10 max-w-sm space-y-1 rounded-xl border border-danger/30 bg-surface p-2 text-xs text-danger shadow-pop">
            {globalProblems.map((p) => (
              <li key={p.message}>{p.message}</li>
            ))}
          </ul>
        )}
        <ReactFlow
          nodes={decorated}
          edges={animatedEdges}
          nodeTypes={NODE_TYPES}
          onNodesChange={readOnly ? undefined : onNodesChange}
          onEdgesChange={readOnly ? undefined : onEdgesChange}
          onConnect={readOnly ? undefined : onConnect}
          isValidConnection={isValidConnection}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          onPaneClick={() => setSelectedId(null)}
          deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} />
          <MiniMap pannable zoomable className="!bg-surface" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <aside aria-label="Node settings" className="scrollbar-thin overflow-y-auto border-t border-line bg-surface p-4 lg:border-t-0 lg:border-l">
        {selected ? (
          <NodeInspector
            id={selected.id}
            type={selected.data.nodeType}
            label={selected.data.label}
            config={selected.data.config}
            retries={selected.data.retries ?? 0}
            onError={selected.data.onError ?? "fail"}
            catalogs={catalogs}
            problems={problemsBy.get(selected.id)}
            output={run?.nodes[selected.id]?.output}
            error={run?.nodes[selected.id]?.error}
            onChange={(patch) =>
              !readOnly &&
              setNodes((c) =>
                c.map((n) => (n.id === selected.id ? { ...n, data: { ...n.data, ...(patch.label !== undefined ? { label: patch.label } : {}), ...(patch.config ? { config: patch.config } : {}), ...(patch.retries !== undefined ? { retries: patch.retries } : {}), ...(patch.onError ? { onError: patch.onError } : {}) } } : n)),
              )
            }
          />
        ) : (
          <p className="text-sm text-muted">Select a node to configure it. Drag from the palette (or click) to add nodes, and connect handles to define the flow.</p>
        )}
      </aside>
    </div>
  );
}
