import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Download, History, Play, Rocket, Save, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { api, errorMessage, followRun } from "../../api/client";
import {
  keys,
  useAgents,
  useCollections,
  useProviders,
  useTools,
  useWorkflow,
  useWorkflowRuns,
  useWorkflowVersions,
} from "../../api/queries";
import type { SpecProblem, Workflow, WorkflowSpec } from "../../api/types";
import { WorkflowEditor } from "../../components/workflow/WorkflowEditor";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Field";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { cn } from "../../lib/cn";
import { slugify } from "../../lib/format";
import { initialRunView, reduceRunEvent, type RunView } from "../../lib/workflowGraph";
import { roleAtLeast, useAuth } from "../auth/auth-context";

export function WorkflowEditorPage() {
  const { workflowId = "" } = useParams();
  const workflow = useWorkflow(workflowId);
  if (workflow.isError) return <ErrorState title="Could not load the workflow" message={errorMessage(workflow.error)} />;
  if (!workflow.data) return <Skeleton className="h-[70vh] rounded-2xl" />;
  return <LoadedEditor key={workflow.data.id} workflow={workflow.data} refetch={() => void workflow.refetch()} />;
}

function LoadedEditor({ workflow: wf, refetch }: { workflow: Workflow; refetch: () => void }) {
  const workflowId = wf.id;
  const { role } = useAuth();
  const canEdit = roleAtLeast(role, "editor");
  const toast = useToast();
  const qc = useQueryClient();
  const agents = useAgents();
  const tools = useTools();
  const collections = useCollections();
  const providers = useProviders();
  const runs = useWorkflowRuns(workflowId);
  const versions = useWorkflowVersions(workflowId);

  const [name, setName] = useState(wf.name);
  const [spec, setSpec] = useState<WorkflowSpec>(wf.spec);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problems, setProblems] = useState<SpecProblem[]>([]);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [runView, setRunView] = useState<RunView | null>(null);
  const [panel, setPanel] = useState<"run" | "versions">("run");
  const abort = useRef<AbortController | null>(null);
  // The editor is uncontrolled after mount; remount it (key) when a version is restored.
  const [editorValue, setEditorValue] = useState<WorkflowSpec>(wf.spec);
  const [editorKey, setEditorKey] = useState(0);

  useEffect(() => () => abort.current?.abort(), []);

  const declaredInputs = useMemo(() => {
    const start = spec?.nodes.find((n) => n.type === "start");
    return ((start?.config.inputs as Array<{ name: string }> | undefined) ?? []).map((i) => i.name).filter(Boolean);
  }, [spec]);

  const onChange = useCallback((next: WorkflowSpec) => {
    setSpec(next);
    setDirty(true);
  }, []);

  const save = async (): Promise<boolean> => {
    setSaving(true);
    try {
      await api.updateWorkflow(workflowId, { name, description: wf.description, spec });
      setDirty(false);
      void qc.invalidateQueries({ queryKey: keys.workflows });
      return true;
    } catch (error) {
      toast.push({ tone: "error", title: "Save failed", description: errorMessage(error) });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const validate = async () => {
    const result = await api.validateWorkflow(spec);
    setProblems(result.problems);
    toast.push(result.valid ? { title: "The workflow is valid" } : { tone: "error", title: `${result.problems.length} problem(s)`, description: result.problems[0]?.message });
    return result.valid;
  };

  const run = async () => {
    if (!(await save()) || !(await validate())) return;
    try {
      const started = await api.startWorkflowRun(workflowId, inputs);
      setPanel("run");
      setRunView({ ...initialRunView, status: "running" });
      const controller = new AbortController();
      abort.current = controller;
      let view = initialRunView;
      for await (const event of followRun(started.id, controller.signal)) {
        view = reduceRunEvent(view, event);
        setRunView(view);
      }
      void qc.invalidateQueries({ queryKey: keys.workflowRuns(workflowId) });
    } catch (error) {
      if (!abort.current?.signal.aborted) toast.push({ tone: "error", title: "Run failed to start", description: errorMessage(error) });
    }
  };

  const exportJson = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ name, description: wf.description, spec }, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slugify(name || "workflow")}.workflow.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const publish = async () => {
    if (!(await save())) return;
    try {
      const v = await api.publishWorkflow(workflowId, "");
      toast.push({ title: `Published version ${v.version}` });
      void versions.refetch();
    } catch (error) {
      toast.push({ tone: "error", title: "Cannot publish", description: errorMessage(error) });
    }
  };

  return (
    <div className="-mx-4 -my-6 flex h-[calc(100vh-3.5rem)] flex-col sm:-mx-8 sm:-my-8 lg:h-screen">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-2.5">
        <Link to="/workflows" aria-label="Back to workflows" className="rounded-lg p-1.5 text-muted hover:bg-surface-2">
          <ArrowLeft className="size-4" />
        </Link>
        <Input aria-label="Workflow name" className="h-8 w-56" value={name} disabled={!canEdit} onChange={(e) => { setName(e.target.value); setDirty(true); }} />
        {dirty ? <Badge tone="warning">unsaved</Badge> : <Badge>saved</Badge>}
        <div className="ml-auto flex flex-wrap gap-1.5">
          <Button size="sm" icon={<CheckCircle2 className="size-4" />} onClick={() => void validate()}>Validate</Button>
          {canEdit && <Button size="sm" icon={<Save className="size-4" />} loading={saving} onClick={() => void save()} disabled={!dirty}>Save</Button>}
          <Button size="sm" variant="ghost" icon={<Download className="size-4" />} aria-label="Export workflow" onClick={exportJson} />
          {canEdit && <Button size="sm" icon={<Rocket className="size-4" />} onClick={() => void publish()}>Publish</Button>}
          <Button size="sm" variant="ghost" icon={<History className="size-4" />} aria-label="Versions" onClick={() => setPanel("versions")} />
        </div>
      </header>
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto]">
        <WorkflowEditor key={editorKey} value={editorValue} onChange={onChange} problems={problems} run={runView} readOnly={!canEdit} catalogs={{
          agents: agents.data ?? [],
          tools: tools.data ?? [],
          collections: collections.data ?? [],
          providers: providers.data ?? [],
        }} />
        <section aria-label="Run panel" className="max-h-64 overflow-y-auto border-t border-line bg-surface px-4 py-3">
          {panel === "versions" ? (
            <div className="text-sm">
              <p className="mb-2 font-medium">Versions</p>
              <ul className="space-y-1">
                {versions.data?.map((v) => (
                  <li key={v.version} className="flex items-center gap-2">
                    <span>v{v.version}</span>
                    <Button size="sm" variant="ghost" onClick={() => void api.restoreWorkflowVersion(workflowId, v.version).then((restored) => { setSpec(restored.spec); setEditorValue(restored.spec); setEditorKey((k) => k + 1); setDirty(false); refetch(); toast.push({ title: `Restored v${v.version}` }); })}>
                      Restore
                    </Button>
                  </li>
                ))}
                {versions.data?.length === 0 && <li className="text-muted">Publish to create version 1.</li>}
              </ul>
              <Button size="sm" variant="ghost" className="mt-2" onClick={() => setPanel("run")}>Back to run</Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-start gap-4">
              <div className="flex flex-wrap items-end gap-2">
                {declaredInputs.map((n) => (
                  <label key={n} className="text-xs">
                    <span className="mb-1 block font-medium">{n}</span>
                    <Input aria-label={`Input ${n}`} className="h-8 w-48" value={inputs[n] ?? ""} onChange={(e) => setInputs({ ...inputs, [n]: e.target.value })} />
                  </label>
                ))}
                {canEdit && (
                  runView?.status === "running" ? (
                    <Button size="sm" variant="danger" icon={<Square className="size-4" />} onClick={() => abort.current?.abort()}>Stop following</Button>
                  ) : (
                    <Button size="sm" variant="primary" icon={<Play className="size-4" />} onClick={() => void run()}>Run</Button>
                  )
                )}
              </div>
              <div className="min-w-0 flex-1">
                {runView ? (
                  <>
                    <p className="text-xs font-medium">
                      Status: <span className={cn(runView.status === "failed" && "text-danger", runView.status === "completed" && "text-success")}>{runView.status}</span>
                      {runView.status === "waiting_approval" && <Link to="/approvals" className="ml-2 text-brand-600 hover:underline">Review on Approvals</Link>}
                    </p>
                    {runView.output !== null && <pre aria-label="Workflow output" className="mt-1 max-h-24 overflow-auto rounded-lg bg-surface-2 p-2 text-xs whitespace-pre-wrap">{runView.output}</pre>}
                    <ol aria-label="Run log" className="mt-1 space-y-0.5 font-mono text-[11px]">
                      {runView.log.map((l) => (
                        <li key={l.seq} className={cn(l.tone === "error" && "text-danger", l.tone === "success" && "text-success", l.tone === "warning" && "text-warning")}>{l.text}</li>
                      ))}
                    </ol>
                  </>
                ) : (
                  <p className="text-xs text-muted">
                    {runs.data?.length ? `${runs.data.length} previous run(s). ` : ""}Fill in the inputs and press Run to watch each node execute.
                  </p>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
