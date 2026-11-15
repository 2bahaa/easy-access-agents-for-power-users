import { FlaskConical, RotateCcw, Rocket, X } from "lucide-react";
import { useMemo, useState } from "react";

import { api, errorMessage } from "../../api/client";
import {
  useAgentVersions,
  useConversation,
  usePublishAgent,
  useRestoreAgentVersion,
} from "../../api/queries";
import type { Agent, AgentVersion } from "../../api/types";
import { AgentChat } from "../../components/AgentChat";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Field, Input } from "../../components/ui/Field";
import { Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { diffAgentConfigs } from "../../lib/configDiff";
import { relativeTime } from "../../lib/format";
import { buildTranscript, liveTranscript } from "../../lib/transcript";
import { useRunStream } from "../chat/useRunStream";
import { AgentAvatar } from "./AgentAvatar";

/** "Draft", "Published v3" or "v3 + unpublished changes". */
export function AgentStatusBadge({ agent }: { agent: Agent }) {
  if (!agent.published_version) return <Badge>Draft · not published</Badge>;
  if (agent.has_unpublished_changes)
    return <Badge tone="warning">v{agent.published_version} live · unpublished changes</Badge>;
  return <Badge tone="success">Published v{agent.published_version}</Badge>;
}

/** Side sheet shell used by the playground and the version history. */
function Sheet({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-[55] flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <button type="button" aria-label="Close" className="absolute inset-0 animate-fade-in bg-black/30" onClick={onClose} />
      <div className={`relative flex h-full w-full ${wide ? "max-w-3xl" : "max-w-xl"} animate-slide-up flex-col border-l border-line bg-surface shadow-pop`}>
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <Button size="sm" variant="ghost" aria-label="Close panel" icon={<X className="size-4" />} onClick={onClose} />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

export function PublishDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const toast = useToast();
  const publish = usePublishAgent(agent.id);
  const [note, setNote] = useState("");
  return (
    <div className="fixed inset-0 z-[55] grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="Publish agent">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <form
        className="relative w-full max-w-md animate-slide-up space-y-4 rounded-2xl border border-line bg-surface p-5 shadow-pop"
        onSubmit={(e) => {
          e.preventDefault();
          publish.mutate(note, {
            onSuccess: (v) => {
              toast.push({ title: `Published version ${v.version}`, description: "Chats now use this version." });
              onClose();
            },
            onError: (error) => toast.push({ tone: "error", title: "Could not publish", description: errorMessage(error) }),
          });
        }}
      >
        <div>
          <h2 className="text-[15px] font-semibold">Publish {agent.name}</h2>
          <p className="mt-1 text-sm text-muted">
            Freezes the current configuration (including skill text) as version {(agent.published_version ?? 0) + 1}. Chats use the latest published version; the playground keeps testing the draft.
          </p>
        </div>
        <Field label="Release note" hint="Optional — what changed?">
          {(p) => <Input {...p} autoFocus value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" icon={<Rocket className="size-4" />} loading={publish.isPending}>
            Publish
          </Button>
        </div>
      </form>
    </div>
  );
}

export function VersionsSheet({ agent, draft, onClose }: { agent: Agent; draft: Record<string, unknown>; onClose: () => void }) {
  const toast = useToast();
  const versions = useAgentVersions(agent.id);
  const restore = useRestoreAgentVersion(agent.id);
  const [open, setOpen] = useState<AgentVersion | null>(null);
  const [loading, setLoading] = useState<number | null>(null);

  const view = async (version: number) => {
    setLoading(version);
    try {
      setOpen(await api.getAgentVersion(agent.id, version));
    } catch (error) {
      toast.push({ tone: "error", title: "Could not load version", description: errorMessage(error) });
    } finally {
      setLoading(null);
    }
  };
  const changes = useMemo(() => (open ? diffAgentConfigs(open.write_config, draft) : []), [open, draft]);

  return (
    <Sheet title="Version history" onClose={onClose} wide>
      {versions.isPending ? (
        <div className="space-y-2 p-5" aria-busy="true">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : versions.isError ? (
        <p className="p-5 text-sm text-danger">{errorMessage(versions.error)}</p>
      ) : versions.data.length === 0 ? (
        <p className="p-5 text-sm text-muted">Not published yet. Publish to create version 1.</p>
      ) : (
        <ul className="divide-y divide-line" aria-label="Versions">
          {versions.data.map((v) => (
            <li key={v.version} className="px-5 py-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">v{v.version}</span>
                {v.version === agent.published_version && <Badge tone="success">live</Badge>}
                <span className="min-w-0 flex-1 truncate text-sm text-muted">{v.note || "No release note"}</span>
                <span className="text-xs text-subtle">{relativeTime(v.created_at)}</span>
                <Button size="sm" loading={loading === v.version} onClick={() => void view(v.version)}>
                  Compare
                </Button>
                <Button
                  size="sm"
                  icon={<RotateCcw className="size-3.5" />}
                  loading={restore.isPending && restore.variables === v.version}
                  onClick={() =>
                    restore.mutate(v.version, {
                      onSuccess: () => toast.push({ title: `Draft restored from v${v.version}`, description: "Publish to make it live." }),
                      onError: (error) => toast.push({ tone: "error", title: "Could not restore", description: errorMessage(error) }),
                    })
                  }
                >
                  Restore to draft
                </Button>
              </div>
              {open?.version === v.version && (
                <div className="mt-3 rounded-xl border border-line" aria-label={`Changes since v${v.version}`}>
                  {changes.length === 0 ? (
                    <p className="p-3 text-sm text-muted">The draft is identical to v{v.version}.</p>
                  ) : (
                    <table className="w-full table-fixed text-left text-xs">
                      <thead className="bg-surface-2 text-subtle">
                        <tr>
                          <th className="w-32 px-3 py-2 font-medium">Field</th>
                          <th className="px-3 py-2 font-medium">v{v.version}</th>
                          <th className="px-3 py-2 font-medium">Draft</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {changes.map((c) => (
                          <tr key={c.field} className="align-top">
                            <td className="px-3 py-2 font-medium">{c.label}</td>
                            <td className="px-3 py-2 break-words whitespace-pre-wrap text-danger">{c.before}</td>
                            <td className="px-3 py-2 break-words whitespace-pre-wrap text-success">{c.after}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}

/** Test the saved draft in a private conversation (not shown in the chat history). */
export function PlaygroundSheet({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const run = useRunStream();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const conversation = useConversation(conversationId ?? undefined);

  const items = useMemo(() => {
    const data = conversation.data;
    const persisted = data ? buildTranscript(data.messages, data.runs) : [];
    if (!run.pending) return persisted;
    const liveId = run.state.runId;
    return [...(liveId ? persisted.filter((i) => i.runId !== liveId) : persisted), ...liveTranscript(run.state, run.pending.content)];
  }, [conversation.data, run.pending, run.state]);

  const send = async (content: string) => {
    setError(null);
    try {
      let id = conversationId;
      if (!id) {
        id = (await api.createConversation(agent.id, true)).id;
        setConversationId(id);
      }
      void run.start(id, content);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <Sheet title={`Playground · ${agent.name}`} onClose={onClose}>
      <div className="flex h-full flex-col">
        <p className="flex items-center gap-2 border-b border-line bg-surface-2/60 px-5 py-2 text-xs text-muted">
          <FlaskConical className="size-3.5" /> Runs the saved draft. Save your changes before testing them.
        </p>
        <div className="min-h-0 flex-1">
          <AgentChat
            items={items}
            draft={run.state.status === "streaming" ? run.state.draft : null}
            running={run.running}
            onSend={(c) => void send(c)}
            onCancel={() => void run.cancel()}
            agentName={agent.name}
            avatar={<AgentAvatar name={agent.name} className="size-8 text-[11px]" />}
            error={error ?? run.sendError}
          />
        </div>
      </div>
    </Sheet>
  );
}

