import { Brain, Database, FileText, Plus, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, errorMessage } from "../../api/client";
import {
  useAgents,
  useClearMemories,
  useCollections,
  useCreateCollection,
  useDeleteCollection,
  useDeleteDocument,
  useDeleteMemory,
  useDocuments,
  useMemories,
  useProviders,
  useUploadDocument,
} from "../../api/queries";
import type { KnowledgeCollection, SearchHit } from "../../api/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { buttonClasses } from "../../components/ui/buttonStyles";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Field, Input, Select } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { cn } from "../../lib/cn";
import { formatBytes, relativeTime } from "../../lib/format";
import { roleAtLeast, useAuth } from "../auth/auth-context";

const STATUS_TONE = { queued: "neutral", processing: "brand", ready: "success", failed: "danger" } as const;

export function KnowledgePage() {
  const [tab, setTab] = useState<"knowledge" | "memory">("knowledge");
  return (
    <>
      <PageHeader
        title="Knowledge & memory"
        description="Document collections agents can search with citations, and what each agent has chosen to remember."
      />
      <div role="tablist" aria-label="Knowledge sections" className="mb-6 flex gap-1 border-b border-line">
        {(
          [
            ["knowledge", "Collections", Database],
            ["memory", "Agent memory", Brain],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium",
              tab === id ? "border-brand-500 text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </div>
      {tab === "knowledge" ? <Collections /> : <Memories />}
    </>
  );
}

function Collections() {
  const { role } = useAuth();
  const canEdit = roleAtLeast(role, "editor");
  const collections = useCollections();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const current = collections.data?.find((c) => c.id === selected) ?? collections.data?.[0];

  if (collections.isPending) return <Skeleton className="h-40 rounded-2xl" />;
  if (collections.isError) return <ErrorState message={errorMessage(collections.error)} onRetry={() => void collections.refetch()} />;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
      <div className="space-y-3">
        {canEdit && !creating && (
          <Button className="w-full" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
            New collection
          </Button>
        )}
        {creating && <NewCollection onDone={(id) => { setCreating(false); if (id) setSelected(id); }} />}
        {collections.data.length === 0 && !creating ? (
          <EmptyState icon={<Database />} title="No collections" description="Create one, then upload documents." />
        ) : (
          <Card>
            <ul aria-label="Collections" className="divide-y divide-line">
              {collections.data.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(c.id)}
                    className={cn("w-full px-4 py-3 text-left hover:bg-surface-2/60", current?.id === c.id && "bg-brand-500/5")}
                  >
                    <span className="block truncate text-sm font-medium">{c.name}</span>
                    <span className="block text-xs text-muted">
                      {c.document_count} docs · {c.chunk_count} chunks · {c.embedding_model}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
      {current && <CollectionDetail key={current.id} collection={current} canEdit={canEdit} />}
    </div>
  );
}

function NewCollection({ onDone }: { onDone: (id?: string) => void }) {
  const create = useCreateCollection();
  const providers = useProviders();
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("nomic-embed-text");
  const usable = (providers.data ?? []).filter((p) => p.kind !== "anthropic");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const conn = usable.find((p) => p.name === provider && !p.builtin);
    create.mutate(
      { name, embedding_model: model, embedding_provider: conn ? "connection" : "ollama", embedding_connection_id: conn?.id ?? null },
      { onSuccess: (c) => onDone(c.id) },
    );
  };
  return (
    <Card className="p-4">
      <form onSubmit={submit} className="space-y-3" aria-label="New collection">
        <Field label="Name">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Embedding provider">
          {(p) => (
            <Select {...p} value={provider} onChange={(e) => setProvider(e.target.value)}>
              {usable.map((x) => (
                <option key={x.name} value={x.name}>
                  {x.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Embedding model" hint="e.g. nomic-embed-text (run: ollama pull nomic-embed-text). Fixed for the collection.">
          {(p) => <Input {...p} value={model} onChange={(e) => setModel(e.target.value)} />}
        </Field>
        {create.isError && <p role="alert" className="text-sm text-danger">{errorMessage(create.error)}</p>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" size="sm" loading={create.isPending} disabled={!name || !model}>
            Create
          </Button>
          <Button size="sm" onClick={() => onDone()}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

function CollectionDetail({ collection: c, canEdit }: { collection: KnowledgeCollection; canEdit: boolean }) {
  const toast = useToast();
  const docs = useDocuments(c.id);
  const upload = useUploadDocument(c.id);
  const removeDoc = useDeleteDocument(c.id);
  const removeCollection = useDeleteCollection();
  const [confirm, setConfirm] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  const runSearch = async (e: FormEvent) => {
    e.preventDefault();
    setSearching(true);
    try {
      setHits(await api.searchKnowledge([c.id], query));
    } catch (error) {
      toast.push({ tone: "error", title: "Search failed", description: errorMessage(error) });
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold tracking-tight">{c.name}</h2>
            <p className="text-xs text-muted">
              {c.embedding_model}
              {c.dims ? ` · ${c.dims} dimensions` : ""} · chunks of {c.chunk_size} chars
            </p>
          </div>
          {canEdit && (
            <>
              <label className={buttonClasses({ variant: "primary", size: "sm" })}>
                <Upload className="size-4" /> Upload
                <input
                  type="file"
                  className="sr-only"
                  aria-label="Upload document"
                  accept=".txt,.md,.markdown,.csv,.json,.log,.rst,.pdf"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file)
                      upload.mutate(file, {
                        onSuccess: () => toast.push({ title: "Uploaded", description: "Indexing in the background." }),
                        onError: (error) => toast.push({ tone: "error", title: "Upload failed", description: errorMessage(error) }),
                      });
                  }}
                />
              </label>
              <Button size="sm" variant="ghost" aria-label="Delete collection" icon={<Trash2 className="size-4" />} onClick={() => setConfirm(true)} />
            </>
          )}
        </div>
        <ul aria-label="Documents" className="mt-4 divide-y divide-line rounded-xl border border-line">
          {docs.data?.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
              <FileText className="size-4 text-subtle" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{d.title}</span>
                <span className="block text-xs text-muted">
                  {formatBytes(d.size_bytes)} · {d.chunk_count} chunks · {relativeTime(d.created_at)}
                  {d.error ? ` · ${d.error}` : ""}
                </span>
              </span>
              <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge>
              {canEdit && d.status === "failed" && (
                <Button size="sm" variant="ghost" aria-label={`Retry ${d.title}`} icon={<RefreshCw className="size-3.5" />} onClick={() => void api.reindexDocument(d.id).then(() => docs.refetch())} />
              )}
              {canEdit && (
                <Button size="sm" variant="ghost" aria-label={`Delete ${d.title}`} icon={<Trash2 className="size-4" />} onClick={() => removeDoc.mutate(d.id)} />
              )}
            </li>
          ))}
          {docs.data?.length === 0 && <li className="px-3 py-4 text-sm text-muted">No documents yet — upload text, Markdown or PDF files.</li>}
        </ul>
      </Card>
      <Card className="p-5">
        <form onSubmit={(e) => void runSearch(e)} className="flex gap-2" aria-label="Search collection">
          <Input aria-label="Search query" placeholder="Try a question…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <Button type="submit" icon={<Search className="size-4" />} loading={searching} disabled={!query.trim()}>
            Search
          </Button>
        </form>
        {hits && (
          <ol aria-label="Search results" className="mt-4 space-y-3">
            {hits.length === 0 && <li className="text-sm text-muted">No relevant passages.</li>}
            {hits.map((h, i) => (
              <li key={`${h.document_id}-${h.chunk}`} className="rounded-xl border border-line p-3">
                <p className="text-xs font-medium text-muted">
                  [{i + 1}] {h.document_title}
                  {h.page ? `, page ${h.page}` : ""}, chunk {h.chunk + 1} · score {h.score}
                </p>
                <p className="mt-1 text-sm whitespace-pre-wrap">{h.text}</p>
              </li>
            ))}
          </ol>
        )}
      </Card>
      <ConfirmDialog
        open={confirm}
        title={`Delete ${c.name}?`}
        message="All documents and their indexed chunks are deleted. Agents using this collection lose access."
        onCancel={() => setConfirm(false)}
        onConfirm={() => removeCollection.mutate(c.id, { onSettled: () => setConfirm(false) })}
      />
    </div>
  );
}

function Memories() {
  const { role } = useAuth();
  const agents = useAgents();
  const [agentId, setAgentId] = useState("");
  const selected = agentId || agents.data?.[0]?.id || "";
  const memories = useMemories(selected || undefined);
  const remove = useDeleteMemory(selected);
  const clear = useClearMemories(selected);
  const canEdit = roleAtLeast(role, "editor");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Agent" className="w-64">
          {(p) => (
            <Select {...p} value={selected} onChange={(e) => setAgentId(e.target.value)}>
              {(agents.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {canEdit && memories.data && memories.data.length > 0 && (
          <Button variant="ghost" icon={<Trash2 className="size-4" />} onClick={() => clear.mutate()}>
            Forget everything
          </Button>
        )}
      </div>
      <p className="text-xs text-muted">Agents remember through the memory tools you grant them. Memories are private to each agent.</p>
      <Card>
        <ul aria-label="Memories" className="divide-y divide-line">
          {memories.data?.map((m) => (
            <li key={m.id} className="flex items-start gap-3 px-5 py-3 text-sm">
              <span className="min-w-0 flex-1">{m.content}</span>
              <span className="text-xs text-subtle">{relativeTime(m.created_at)}</span>
              {canEdit && <Button size="sm" variant="ghost" aria-label="Forget this memory" icon={<Trash2 className="size-4" />} onClick={() => remove.mutate(m.id)} />}
            </li>
          ))}
          {memories.data?.length === 0 && <li className="px-5 py-4 text-sm text-muted">This agent has not remembered anything yet.</li>}
        </ul>
      </Card>
    </div>
  );
}
