import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ApiError, errorMessage } from "../../api/client";
import {
  useAgent,
  useDeleteAgent,
  useModels,
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
import { emptyAgentForm, fromAgent } from "../../lib/agentForm";
import { AgentAvatar } from "./AgentAvatar";

export function AgentEditorPage() {
  const { agentId } = useParams();
  const isNew = !agentId;
  const navigate = useNavigate();
  const toast = useToast();

  const agent = useAgent(agentId);
  const skills = useSkills();
  const tools = useTools();
  const provider = agent.data?.provider ?? "ollama";
  const models = useModels(provider);
  const save = useSaveAgent();
  const remove = useDeleteAgent();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const initialValues = useMemo(
    () => (agent.data ? fromAgent(agent.data) : emptyAgentForm()),
    [agent.data],
  );

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
          isNew
            ? "Configure the model, instructions, skills and tools, then save."
            : "Edit configuration. Changes apply to new runs."
        }
        actions={
          !isNew &&
          agentId && (
            <LinkButton
              to={`/agents/${agentId}/chat`}
              variant="primary"
              icon={<MessageSquare className="size-4" />}
            >
              Open chat
            </LinkButton>
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
          key={agent.data?.updated_at ?? "new"}
          initialValues={initialValues}
          isNew={isNew}
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
