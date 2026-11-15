import { GitFork, Plus, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api, errorMessage } from "../../api/client";
import { useDeleteWorkflow, useWorkflows, useWorkflowTemplates } from "../../api/queries";
import type { WorkflowSpec } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { buttonClasses } from "../../components/ui/buttonStyles";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { relativeTime } from "../../lib/format";
import { roleAtLeast, useAuth } from "../auth/auth-context";

const BLANK: WorkflowSpec = {
  schema_version: 1,
  nodes: [
    { id: "start", type: "start", label: "Start", config: { inputs: [{ name: "text", description: "" }] }, position: { x: 0, y: 80 } },
    { id: "end", type: "end", label: "End", config: { output: "{{ input.text }}" }, position: { x: 420, y: 80 } },
  ],
  edges: [{ source: "start", target: "end", source_handle: null }],
};

export function WorkflowsPage() {
  const { role } = useAuth();
  const canEdit = roleAtLeast(role, "editor");
  const workflows = useWorkflows();
  const templates = useWorkflowTemplates();
  const remove = useDeleteWorkflow();
  const navigate = useNavigate();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [toDelete, setToDelete] = useState<{ id: string; name: string } | null>(null);

  const create = async (name: string, spec: WorkflowSpec, description = "") => {
    try {
      const wf = await api.createWorkflow({ name, description, spec });
      navigate(`/workflows/${wf.id}`);
    } catch (error) {
      toast.push({ tone: "error", title: "Could not create workflow", description: errorMessage(error) });
    }
  };

  const importFile = async (file: File) => {
    try {
      const doc = JSON.parse(await file.text()) as { name?: string; description?: string; spec?: WorkflowSpec };
      if (!doc.spec) throw new Error("Missing spec");
      await create(doc.name ?? file.name.replace(/\.json$/, ""), doc.spec, doc.description ?? "");
    } catch (error) {
      toast.push({ tone: "error", title: "Import failed", description: error instanceof SyntaxError ? "The file is not valid JSON." : errorMessage(error) });
    }
  };

  return (
    <>
      <PageHeader
        title="Workflows"
        description="Chain agents, models, tools, knowledge and human approvals on a visual canvas."
        actions={
          canEdit && (
            <>
              <label className={buttonClasses({ variant: "secondary" })}>
                <Upload className="size-4" />
                <span className="hidden sm:inline">Import</span>
                <input
                  type="file"
                  accept="application/json,.json"
                  className="sr-only"
                  aria-label="Import workflow"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) void importFile(f);
                  }}
                />
              </label>
              <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating((v) => !v)}>
                New workflow
              </Button>
            </>
          )
        }
      />
      {creating && (
        <Card className="mb-6 p-5">
          <p className="mb-3 text-sm font-medium">Start from</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <button type="button" onClick={() => void create("Untitled workflow", BLANK)} className="rounded-xl border border-dashed border-line-strong p-4 text-left hover:border-brand-500">
              <span className="block text-sm font-semibold">Blank</span>
              <span className="block text-xs text-muted">Start → End</span>
            </button>
            {templates.data?.map((t) => (
              <button key={t.id} type="button" onClick={() => void create(t.name, t.spec, t.description)} className="rounded-xl border border-line p-4 text-left hover:border-brand-500">
                <span className="block text-sm font-semibold">{t.name}</span>
                <span className="block text-xs text-muted">{t.description}</span>
              </button>
            ))}
          </div>
        </Card>
      )}
      {workflows.isPending ? (
        <Skeleton className="h-32 rounded-2xl" />
      ) : workflows.isError ? (
        <ErrorState message={errorMessage(workflows.error)} onRetry={() => void workflows.refetch()} />
      ) : workflows.data.length === 0 ? (
        <EmptyState icon={<GitFork />} title="No workflows yet" description="Create one from a template to see how steps connect." />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Workflows">
          {workflows.data.map((w) => (
            <li key={w.id}>
              <Card className="flex h-full flex-col p-5">
                <Link to={`/workflows/${w.id}`} className="text-base font-semibold hover:underline">
                  {w.name}
                </Link>
                <p className="mt-1 line-clamp-2 flex-1 text-sm text-muted">{w.description || "No description"}</p>
                <div className="mt-3 flex items-center justify-between text-xs text-subtle">
                  <span>
                    {w.node_count} nodes · edited {relativeTime(w.updated_at)}
                  </span>
                  {canEdit && (
                    <Button size="sm" variant="ghost" aria-label={`Delete ${w.name}`} icon={<Trash2 className="size-4" />} onClick={() => setToDelete({ id: w.id, name: w.name })} />
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={!!toDelete}
        title={`Delete ${toDelete?.name}?`}
        message="The workflow, its versions and its run history are deleted."
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete.id, { onSettled: () => setToDelete(null) })}
      />
    </>
  );
}
