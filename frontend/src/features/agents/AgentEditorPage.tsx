import { Copy, Download, FlaskConical, History, MessageSquare, Plus, Rocket, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api, ApiError, errorMessage } from "../../api/client";
import {
  useAgent,
  useAgentTemplates,
  useDeleteAgent,
  useDuplicateAgent,
  useModels,
  useProviders,
  useSaveAgent,
  useSkills,
  useTools,
} from "../../api/queries";
import type { AgentWrite } from "../../api/types";
import { AgentBuilder } from "../../components/AgentBuilder";
import { Button } from "../../components/ui/Button";
import { LinkButton } from "../../components/ui/LinkButton";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { emptyAgentForm, fromAgent, toAgentWrite } from "../../lib/agentForm";
import { slugify } from "../../lib/format";
import { AgentAvatar } from "./AgentAvatar";
import { AgentStatusBadge, PlaygroundSheet, PublishDialog, VersionsSheet } from "./AgentLifecycle";

export function AgentEditorPage() {
  const { agentId } = useParams();
  const isNew = !agentId;
  const navigate = useNavigate();
  const toast = useToast();

  const agent = useAgent(agentId);
  const skills = useSkills();
  const tools = useTools();
  const providers = useProviders();
  const [providerOverride, setProviderOverride] = useState<string | null>(null);
  const provider = providerOverride ?? agent.data?.connection_id ?? agent.data?.provider ?? "ollama";
  const models = useModels(provider);
  const save = useSaveAgent();
  const remove = useDeleteAgent();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [params] = useSearchParams();
  const templates = useAgentTemplates();
  const template = isNew ? templates.data?.find((t) => t.id === params.get("template")) : undefined;
  const [sheet, setSheet] = useState<"publish" | "versions" | "playground" | null>(null);
  const duplicate = useDuplicateAgent();

  const initialValues = useMemo(() => {
    if (agent.data) return fromAgent(agent.data);
    const base = emptyAgentForm();
    if (!template) return base;
    const suggested = (skills.data ?? []).filter((s) => template.suggested_skills.includes(s.slug)).map((s) => s.id);
    return {
      ...base,
      name: template.name,
      description: template.description,
      systemPrompt: template.system_prompt,
      tools: template.tools.map((t) => ({ name: t.name, config: { ...t.config } })),
      temperature: template.model_params.temperature ?? null,
      maxToolCalls: template.max_tool_calls,
      runTimeoutS: template.run_timeout_s,
      skillIds: suggested,
    };
  }, [agent.data, template, skills.data]);

  const exportJson = async () => {
    if (!agentId) return;
    try {
      const doc = await api.exportAgent(agentId);
      const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${slugify(agent.data?.name ?? "agent")}.agent.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.push({ tone: "error", title: "Export failed", description: errorMessage(error) });
    }
  };

  const loading = (!isNew && agent.isPending) || skills.isPending || tools.isPending;
  const loadError = agent.error ?? skills.error ?? tools.error;

  const handleSubmit = (data: AgentWrite) => {
    save.mutate(
      { id: agentId, data },
      {
        onSuccess: (saved) => {
          toast.push({ title: isNew ? "Agent created" : "Agent saved", description: saved.name });
          if (isNew) navigate(`/agents/${saved.id}`, { replace: true });
        },
      },
    );
  };

  const handleDelete = () => {
    if (!agentId) return;
    remove.mutate(agentId, {
      onSuccess: () => {
        toast.push({ title: "Agent deleted" });
        navigate("/agents", { replace: true });
      },
      onError: (err) => {
        setConfirmDelete(false);
        toast.push({ tone: "error", title: "Could not delete agent", description: errorMessage(err) });
      },
    });
  };

  const saveError = save.error instanceof ApiError ? save.error : null;

  return (
    <>
      <PageHeader
        breadcrumb={{ label: "Agents", to: "/agents" }}
        title={
          isNew ? (
            "New agent"
          ) : agent.data ? (
            <span className="flex items-center gap-3">
              <AgentAvatar name={agent.data.name} className="size-9 text-xs" />
              {agent.data.name}
            </span>
          ) : (
            "Agent"
          )
        }
        description={
          isNew ? (
            template ? `Started from the "${template.name}" template — choose a model and save.` : "Configure the model, instructions, skills and tools, then save."
          ) : agent.data ? (
            <span className="flex flex-wrap items-center gap-2">
              <AgentStatusBadge agent={agent.data} />
              <span>You edit the draft; publish to update chats.</span>
            </span>
          ) : null
        }
        actions={
          !isNew &&
          agentId &&
          agent.data && (
            <div className="flex flex-wrap items-center gap-2">
              <Button icon={<FlaskConical className="size-4" />} onClick={() => setSheet("playground")}>
                Test
              </Button>
              <Button icon={<History className="size-4" />} onClick={() => setSheet("versions")} aria-label="Version history">
                <span className="hidden md:inline">History</span>
              </Button>
              <Button
                icon={<Copy className="size-4" />}
                aria-label="Duplicate agent"
                loading={duplicate.isPending}
                onClick={() =>
                  duplicate.mutate(agentId, {
                    onSuccess: (copy) => {
                      toast.push({ title: "Agent duplicated", description: copy.name });
                      navigate(`/agents/${copy.id}`);
                    },
                    onError: (error) => toast.push({ tone: "error", title: "Could not duplicate", description: errorMessage(error) }),
                  })
                }
              />
              <Button icon={<Download className="size-4" />} aria-label="Export agent" onClick={() => void exportJson()} />
              <Button variant="primary" icon={<Rocket className="size-4" />} onClick={() => setSheet("publish")}>
                Publish
              </Button>
              <LinkButton to={`/agents/${agentId}/chat`} icon={<MessageSquare className="size-4" />}>
                Chat
              </LinkButton>
            </div>
          )
        }
      />

      {loadError && <ErrorState title="Could not load the editor" message={errorMessage(loadError)} />}

      {loading && !loadError && (
        <div className="grid gap-5 lg:grid-cols-5" aria-busy="true">
          <div className="space-y-5 lg:col-span-3">
            <Skeleton className="h-48 rounded-2xl" />
            <Skeleton className="h-72 rounded-2xl" />
          </div>
          <div className="space-y-5 lg:col-span-2">
            <Skeleton className="h-80 rounded-2xl" />
            <Skeleton className="h-56 rounded-2xl" />
          </div>
        </div>
      )}

      {!loading && !loadError && skills.data && tools.data && (
        <AgentBuilder
          key={agent.data?.updated_at ?? `new-${template?.id ?? ""}`}
          initialValues={initialValues}
          isNew={isNew}
          providers={providers.data}
          onProviderChange={setProviderOverride}
          models={models.data}
          modelsLoading={models.isPending}
          modelsUnavailable={models.isError ? errorMessage(models.error) : undefined}
          skills={skills.data}
          tools={tools.data}
          onSubmit={handleSubmit}
          submitting={save.isPending}
          serverError={save.isError ? errorMessage(save.error) : null}
          serverFieldErrors={saveError?.fieldErrors()}
          submitLabel={isNew ? "Create agent" : "Save changes"}
          emptySkillsAction={
            <LinkButton to="/skills/new" size="sm" icon={<Plus className="size-3.5" />
              }>
                Create a skill
            </LinkButton>
          }
          secondaryActions={
            !isNew && (
              <Button
                variant="ghost"
                icon={<Trash2 className="size-4" />}
                onClick={() => setConfirmDelete(true)}
                className="hover:text-red-600"
              >
                <span className="hidden sm:inline">Delete</span>
              </Button>
            )
          }
        />
      )}

      {agent.data && sheet === "publish" && <PublishDialog agent={agent.data} onClose={() => setSheet(null)} />}
      {agent.data && sheet === "versions" && (
        <VersionsSheet
          agent={agent.data}
          draft={toAgentWrite(fromAgent(agent.data)) as unknown as Record<string, unknown>}
          onClose={() => setSheet(null)}
        />
      )}
      {agent.data && sheet === "playground" && <PlaygroundSheet agent={agent.data} onClose={() => setSheet(null)} />}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this agent?"
        message="Its conversations and run history will be deleted too. This cannot be undone."
        loading={remove.isPending}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  );
}
