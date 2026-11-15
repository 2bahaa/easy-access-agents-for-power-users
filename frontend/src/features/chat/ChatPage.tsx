import { Activity, ArrowLeft, History, Plus, Settings2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { errorMessage } from "../../api/client";
import {
  useAgent,
  useApprovals,
  useConversation,
  useConversations,
  useCreateConversation,
  useDecideApproval,
  useDeleteConversation,
  useRunEvents,
} from "../../api/queries";
import type { Agent, ConversationSummary } from "../../api/types";
import { AgentChat } from "../../components/AgentChat";
import { ApprovalCard } from "../../components/ApprovalCard";
import { AgentRunTimeline } from "../../components/AgentRunTimeline";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { LinkButton } from "../../components/ui/LinkButton";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { cn } from "../../lib/cn";
import { replayRunEvents } from "../../lib/runReducer";
import { buildTranscript, liveTranscript } from "../../lib/transcript";
import { AgentAvatar } from "../agents/AgentAvatar";
import { roleAtLeast, useAuth } from "../auth/auth-context";
import { ConversationList } from "./ConversationList";
import { useRunStream } from "./useRunStream";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function suggestionsFor(agent: Agent | undefined): string[] {
  const tools = new Set(agent?.tools.map((t) => t.name));
  const out: string[] = [];
  if (tools.has("calculator")) out.push("What is 17.5 * 23 + 4?");
  if (tools.has("file_reader")) out.push("Read notes.txt and summarize it.");
  out.push("What can you help me with?");
  if (out.length < 4) out.push("Introduce yourself in two sentences.");
  return out.slice(0, 4);
}

export function ChatPage() {
  const { agentId = "", conversationId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const agent = useAgent(agentId);
  const conversations = useConversations(agentId);
  const conversation = useConversation(conversationId);
  const createConversation = useCreateConversation();
  const deleteConversation = useDeleteConversation(agentId);
  const run = useRunStream();
  const { role } = useAuth();
  const canDecide = roleAtLeast(role, "editor");
  const pendingApprovals = useApprovals({ status: "pending", conversation_id: conversationId }, !!conversationId);
  const decide = useDecideApproval();

  const [selection, setSelection] = useState<{ conversationId?: string; runId: string } | null>(null);
  const [panel, setPanel] = useState<"history" | "timeline" | null>(null);
  const [toDelete, setToDelete] = useState<ConversationSummary | null>(null);

  // Reattach to a run that is still active on the server (page reload, navigation back,
  // another tab started it). Each run is attached at most once per page instance.
  const attachedRef = useRef(new Set<string>());
  const lastRun = conversation.data?.runs.at(-1);
  const { attach, pending } = run;
  useEffect(() => {
    if (!conversationId || pending || !lastRun) return;
    if (lastRun.status !== "queued" && lastRun.status !== "running") return;
    if (attachedRef.current.has(lastRun.id)) return;
    attachedRef.current.add(lastRun.id);
    const prompt = conversation.data?.messages.find((m) => m.role === "user" && m.run_id === lastRun.id);
    void attach(conversationId, lastRun.id, prompt?.content ?? "");
  }, [attach, conversation.data, conversationId, lastRun, pending]);

  const liveHere = !!run.pending && run.pending.conversationId === conversationId;
  const liveRunId = liveHere ? run.state.runId : null;

  const items = useMemo(() => {
    const data = conversation.data;
    const persisted = data ? buildTranscript(data.messages, data.runs) : [];
    if (!liveHere || !run.pending) return persisted;
    // Avoid showing a run twice while the refetched transcript replaces the live view.
    const filtered = liveRunId ? persisted.filter((i) => i.runId !== liveRunId) : persisted;
    return [...filtered, ...liveTranscript(run.state, run.pending.content)];
  }, [conversation.data, liveHere, liveRunId, run.pending, run.state]);

  // Timeline: explicit selection > live run > most recent run of this conversation.
  const lastRunId = conversation.data?.runs.at(-1)?.id;
  const selectedRunId =
    (selection && selection.conversationId === conversationId ? selection.runId : null) ??
    liveRunId ??
    (liveHere ? null : lastRunId) ??
    null;
  const showingLive = liveHere && (selectedRunId === liveRunId || selectedRunId === null);
  const runEvents = useRunEvents(selectedRunId ?? undefined, !showingLive);
  const timeline = useMemo(() => {
    if (showingLive) return { items: run.state.items, status: run.state.status };
    if (selectedRunId && runEvents.data) return replayRunEvents(selectedRunId, runEvents.data);
    return { items: [], status: "idle" as const };
  }, [showingLive, run.state, selectedRunId, runEvents.data]);

  const handleSend = async (content: string) => {
    setSelection(null);
    run.clearSendError();
    if (conversationId) {
      void run.start(conversationId, content);
      return;
    }
    try {
      const created = await createConversation.mutateAsync(agentId);
      navigate(`/agents/${agentId}/chat/${created.id}`);
      void run.start(created.id, content);
    } catch (error) {
      toast.push({ tone: "error", title: "Could not start a conversation", description: errorMessage(error) });
    }
  };

  const handleDelete = () => {
    if (!toDelete) return;
    const target = toDelete;
    deleteConversation.mutate(target.id, {
      onSuccess: () => {
        setToDelete(null);
        toast.push({ title: "Conversation deleted" });
        if (target.id === conversationId) navigate(`/agents/${agentId}/chat`);
      },
      onError: (error) => {
        setToDelete(null);
        toast.push({ tone: "error", title: "Could not delete conversation", description: errorMessage(error) });
      },
    });
  };

  if (agent.isError) {
    return (
      <div className="space-y-4">
        <ErrorState title="Could not load this agent" message={errorMessage(agent.error)} />
        <LinkButton to="/agents" icon={<ArrowLeft className="size-4" />}>
          Back to agents
        </LinkButton>
      </div>
    );
  }

  const agentName = agent.data?.name ?? "Agent";
  const avatar = <AgentAvatar name={agentName} className="size-8 text-[11px]" />;
  const conversationMissing = !!conversationId && conversation.isError;

  const history = (
    <ConversationList
      agentId={agentId}
      conversations={conversations.data}
      loading={conversations.isPending}
      activeId={conversationId}
      onNew={() => {
        setPanel(null);
        navigate(`/agents/${agentId}/chat`);
      }}
      onDelete={setToDelete}
    />
  );

  const timelinePanel = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <p className="text-sm font-semibold">Run timeline</p>
          <p className="text-xs text-muted">
            {showingLive && run.state.status === "streaming" ? "Live" : selectedRunId ? "Selected run" : "No runs yet"}
          </p>
        </div>
        {showingLive && run.state.status === "streaming" && (
          <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
            <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" /> live
          </span>
        )}
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
        <AgentRunTimeline
          items={timeline.items}
          status={timeline.status}
          loading={!showingLive && !!selectedRunId && runEvents.isPending}
          emptyText="Send a message to see the agent's steps here."
        />
      </div>
    </div>
  );

  return (
    <div className="-mx-4 -my-6 sm:-mx-8 sm:-my-8">
      <div className="relative grid h-[calc(100dvh-3.5rem)] grid-cols-1 overflow-hidden bg-surface lg:h-dvh lg:grid-cols-[260px_minmax(0,1fr)] xl:grid-cols-[260px_minmax(0,1fr)_380px]">
        <aside aria-label="Conversation history" className="hidden min-h-0 border-r border-line bg-canvas/50 lg:block">
          {history}
        </aside>

        <section aria-label="Chat" className="flex min-h-0 flex-col">
          <header className="flex items-center gap-3 border-b border-line px-4 py-3 sm:px-6">
            {agent.isPending ? (
              <Skeleton className="h-8 w-48" />
            ) : (
              <>
                {avatar}
                <div className="min-w-0 flex-1">
                  <h1 className="truncate text-sm font-semibold">{agentName}</h1>
                  <p className="truncate text-xs text-muted">
                    <span className="font-mono">{agent.data?.model}</span>
                    {agent.data && agent.data.tools.length > 0 && <> · {plural(agent.data.tools.length, "tool")}</>}
                    {agent.data && agent.data.skills.length > 0 && <> · {plural(agent.data.skills.length, "skill")}</>}
                  </p>
                </div>
              </>
            )}
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" className="lg:hidden" aria-label="Show history" icon={<History className="size-4" />} onClick={() => setPanel("history")} />
              <Button size="sm" variant="ghost" className="xl:hidden" aria-label="Show run timeline" icon={<Activity className="size-4" />} onClick={() => setPanel("timeline")} />
              <LinkButton to={`/agents/${agentId}`} size="sm" variant="ghost" icon={<Settings2 className="size-4" />}>
                <span className="hidden sm:inline">Configure</span>
              </LinkButton>
              <Button size="sm" variant="secondary" icon={<Plus className="size-4" />} onClick={() => navigate(`/agents/${agentId}/chat`)} className="hidden sm:inline-flex">
                New chat
              </Button>
            </div>
          </header>

          <div className="min-h-0 flex-1">
            {conversationMissing ? (
              <div className="p-6">
                <ErrorState title="Conversation not found" message={errorMessage(conversation.error)} />
                <Link to={`/agents/${agentId}/chat`} className="mt-3 inline-block text-sm text-brand-600 hover:underline">
                  Start a new chat
                </Link>
              </div>
            ) : (
              <div className="flex h-full min-h-0 flex-col">
              {conversationId && pendingApprovals.data && pendingApprovals.data.length > 0 && (
                <div className="space-y-3 border-b border-line p-4" aria-label="Pending approvals">
                  {pendingApprovals.data.map((a) => (
                    <ApprovalCard
                      key={a.id}
                      approval={a}
                      busy={decide.isPending && decide.variables?.id === a.id}
                      disabled={!canDecide}
                      onDecide={(d) =>
                        decide.mutate(
                          { id: a.id, ...d },
                          {
                            onError: (error) =>
                              toast.push({ tone: "error", title: "Decision failed", description: errorMessage(error) }),
                          },
                        )
                      }
                    />
                  ))}
                </div>
              )}
              <div className="min-h-0 flex-1">
              <AgentChat
                items={items}
                draft={liveHere && run.state.status === "streaming" ? run.state.draft : null}
                running={run.running}
                onSend={(content) => void handleSend(content)}
                onCancel={() => void run.cancel()}
                agentName={agentName}
                avatar={avatar}
                suggestions={suggestionsFor(agent.data)}
                onSelectRun={(runId) => {
                  setSelection({ conversationId, runId });
                  if (window.matchMedia?.("(max-width: 1279px)").matches) setPanel("timeline");
                }}
                selectedRunId={selectedRunId}
                error={run.sendError}
                loading={!!conversationId && conversation.isPending}
                disabledReason={agent.isPending ? "Loading agent…" : undefined}
              />
              </div>
              </div>
            )}
          </div>
        </section>

        <aside aria-label="Run details" className="hidden min-h-0 border-l border-line bg-canvas/50 xl:block">
          {timelinePanel}
        </aside>

        {panel && (
          <div className="absolute inset-0 z-20 flex animate-fade-in" role="dialog" aria-label={panel === "history" ? "History" : "Run timeline"}>
            <div className="absolute inset-0 bg-black/30" onClick={() => setPanel(null)} />
            <div
              className={cn(
                "relative flex h-full w-[min(380px,90vw)] flex-col border-line bg-surface shadow-pop",
                panel === "timeline" ? "ml-auto border-l" : "border-r",
              )}
            >
              <button
                type="button"
                aria-label="Close panel"
                onClick={() => setPanel(null)}
                className="absolute top-2.5 right-2.5 z-10 rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
              >
                <X className="size-4" />
              </button>
              {panel === "history" ? history : timelinePanel}
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!toDelete}
        title="Delete this conversation?"
        message={`"${toDelete?.title ?? ""}" and its run history will be permanently deleted.`}
        loading={deleteConversation.isPending}
        onConfirm={handleDelete}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}
