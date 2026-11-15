import { ChevronDown, ChevronRight, FlaskConical, Plug, Plus, RefreshCw, Server, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { errorMessage } from "../../api/client";
import {
  useCreateProvider,
  useDeleteProvider,
  useModels,
  useProbeModel,
  useProviders,
  useSetModelTools,
  useTestProvider,
} from "../../api/queries";
import type { ModelInfo, ProviderInfo, ProviderKind } from "../../api/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Field, Input, Select } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { relativeTime } from "../../lib/format";
import { roleAtLeast, useAuth } from "../auth/auth-context";

const KINDS: Array<{ kind: ProviderKind; label: string; needsKey: boolean; needsUrl: boolean; urlHint?: string }> = [
  { kind: "openai", label: "OpenAI", needsKey: true, needsUrl: false },
  { kind: "anthropic", label: "Anthropic", needsKey: true, needsUrl: false },
  { kind: "gemini", label: "Google Gemini", needsKey: true, needsUrl: false },
  {
    kind: "openai_compatible",
    label: "OpenAI-compatible (Hugging Face, vLLM, LM Studio…)",
    needsKey: false,
    needsUrl: true,
    urlHint: "e.g. http://127.0.0.1:1234/v1 or https://router.huggingface.co/v1",
  },
  { kind: "ollama", label: "Ollama (another server)", needsKey: false, needsUrl: true, urlHint: "e.g. http://192.168.1.20:11434" },
];

function StatusBadge({ p }: { p: ProviderInfo }) {
  if (p.status === "ok") return <Badge tone="success">Connected</Badge>;
  if (p.status === "error") return <Badge tone="danger">Unreachable</Badge>;
  return <Badge>Not checked</Badge>;
}

export function ProvidersPage() {
  const { role } = useAuth();
  const isAdmin = roleAtLeast(role, "admin");
  const providers = useProviders();
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader
        title="Providers & models"
        description="Connect model providers. API keys are encrypted on the server and never shown again."
        actions={
          isAdmin && !adding ? (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
              Add provider
            </Button>
          ) : null
        }
      />
      {adding && <AddProviderForm onDone={() => setAdding(false)} />}
      {providers.isPending ? (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : providers.isError ? (
        <ErrorState message={errorMessage(providers.error)} onRetry={() => void providers.refetch()} />
      ) : providers.data.length === 0 ? (
        <EmptyState icon={<Plug />} title="No providers" description="Add a provider to run agents on hosted models." />
      ) : (
        <div className="space-y-3">
          {providers.data.map((p) => (
            <ProviderCard key={p.name} provider={p} canManage={isAdmin} canEdit={roleAtLeast(role, "editor")} />
          ))}
        </div>
      )}
    </>
  );
}

function AddProviderForm({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const create = useCreateProvider();
  const [kind, setKind] = useState<ProviderKind>("openai");
  const [name, setName] = useState("OpenAI");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const meta = KINDS.find((k) => k.kind === kind)!;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { name, kind, base_url: baseUrl || null, api_key: apiKey || null },
      {
        onSuccess: (p) => {
          toast.push({ title: "Provider added", description: p.label });
          onDone();
        },
      },
    );
  };

  return (
    <Card className="mb-6 p-5">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" aria-label="Add provider">
        <Field label="Type">
          {(p) => (
            <Select
              {...p}
              value={kind}
              onChange={(e) => {
                const next = e.target.value as ProviderKind;
                setKind(next);
                setName(KINDS.find((k) => k.kind === next)!.label.split(" (")[0]!);
              }}
            >
              {KINDS.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Display name">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Base URL" hint={meta.needsUrl ? meta.urlHint : "Optional: leave empty for the official endpoint."} required={meta.needsUrl}>
          {(p) => <Input {...p} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={meta.urlHint?.replace("e.g. ", "")} />}
        </Field>
        <Field label="API key" hint="Write-only. Stored encrypted; only the last 4 characters are shown." required={meta.needsKey}>
          {(p) => <Input {...p} type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />}
        </Field>
        {create.isError && (
          <p role="alert" className="text-sm text-danger sm:col-span-2">
            {errorMessage(create.error)}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <Button
            type="submit"
            variant="primary"
            loading={create.isPending}
            disabled={!name || (meta.needsKey && !apiKey) || (meta.needsUrl && !baseUrl)}
          >
            Save provider
          </Button>
          <Button onClick={onDone}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}

function ProviderCard({ provider: p, canManage, canEdit }: { provider: ProviderInfo; canManage: boolean; canEdit: boolean }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const test = useTestProvider();
  const remove = useDeleteProvider();

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 px-5 py-4">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} models of ${p.label}`}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          {open ? <ChevronDown className="size-4 text-subtle" /> : <ChevronRight className="size-4 text-subtle" />}
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
            {p.builtin ? <Server className="size-4" /> : <Plug className="size-4" />}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold">{p.label}</span>
            <span className="block truncate text-xs text-muted">
              {p.kind}
              {p.base_url ? ` · ${p.base_url}` : ""}
              {p.has_secret ? ` · key ${p.secret_hint ?? ""}` : ""}
              {p.last_checked_at ? ` · checked ${relativeTime(p.last_checked_at)}` : ""}
            </span>
          </span>
        </button>
        <StatusBadge p={p} />
        <Button
          size="sm"
          icon={<RefreshCw className="size-3.5" />}
          loading={test.isPending}
          onClick={() =>
            test.mutate(p.name, {
              onSuccess: (r) =>
                toast.push(
                  r.status === "ok"
                    ? { title: `${p.label} is reachable` }
                    : { tone: "error", title: `${p.label} is unreachable`, description: r.last_error ?? undefined },
                ),
            })
          }
        >
          Test
        </Button>
        {!p.builtin && canManage && (
          <Button size="sm" variant="ghost" aria-label={`Delete ${p.label}`} icon={<Trash2 className="size-4" />} onClick={() => setConfirm(true)} />
        )}
      </div>
      {p.status === "error" && p.last_error && <p className="px-5 pb-3 text-xs text-danger">{p.last_error}</p>}
      {open && <ModelTable provider={p.name} canEdit={canEdit} />}
      <ConfirmDialog
        open={confirm}
        title={`Delete ${p.label}?`}
        message="Agents using this provider must be switched first. The stored API key is deleted."
        loading={remove.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() =>
          remove.mutate(p.name, {
            onSettled: () => setConfirm(false),
            onError: (error) => toast.push({ tone: "error", title: "Could not delete provider", description: errorMessage(error) }),
          })
        }
      />
    </Card>
  );
}

function ToolsCell({ m }: { m: ModelInfo }) {
  const source = m.tools_source === "probe" ? " (checked)" : m.tools_source === "user" ? " (set manually)" : "";
  if (m.supports_tools === true) return <Badge tone="success">Tools{source}</Badge>;
  if (m.supports_tools === false) return <Badge>No tools{source}</Badge>;
  return <Badge tone="warning">Unknown</Badge>;
}

function ModelTable({ provider, canEdit }: { provider: string; canEdit: boolean }) {
  const toast = useToast();
  const models = useModels(provider);
  const probe = useProbeModel(provider);
  const setTools = useSetModelTools(provider);
  const [filter, setFilter] = useState("");

  if (models.isPending)
    return (
      <div className="border-t border-line p-5" aria-busy="true">
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  if (models.isError)
    return <p className="border-t border-line px-5 py-4 text-sm text-danger">{errorMessage(models.error)}</p>;

  const shown = models.data.filter((m) => m.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="border-t border-line">
      {models.data.length > 8 && (
        <div className="px-5 pt-4">
          <Input aria-label="Filter models" placeholder="Filter models…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
      )}
      <ul className="divide-y divide-line" aria-label={`Models of ${provider}`}>
        {shown.map((m) => (
          <li key={m.name} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-mono text-[13px]">{m.name}</span>
              {(m.display_name || m.context_window) && (
                <span className="block text-xs text-subtle">
                  {m.display_name}
                  {m.context_window ? ` · ${m.context_window.toLocaleString()} tokens context` : ""}
                </span>
              )}
            </span>
            <ToolsCell m={m} />
            {canEdit && m.tools_source !== "provider" && (
              <>
                <Button
                  size="sm"
                  icon={<FlaskConical className="size-3.5" />}
                  loading={probe.isPending && probe.variables === m.name}
                  title="Sends one small request asking the model to call a test tool"
                  onClick={() =>
                    probe.mutate(m.name, {
                      onSuccess: (r) => toast.push({ title: r.supports_tools ? "Tool calling works" : "No tool call", description: r.detail }),
                      onError: (error) => toast.push({ tone: "error", title: "Check failed", description: errorMessage(error) }),
                    })
                  }
                >
                  Check tools
                </Button>
                <Select
                  aria-label={`Tool support of ${m.name}`}
                  className="w-36"
                  value={m.tools_source === "user" ? String(m.supports_tools) : ""}
                  onChange={(e) =>
                    setTools.mutate({ model: m.name, supportsTools: e.target.value === "" ? null : e.target.value === "true" })
                  }
                >
                  <option value="">Auto</option>
                  <option value="true">Supports tools</option>
                  <option value="false">No tools</option>
                </Select>
              </>
            )}
          </li>
        ))}
        {shown.length === 0 && <li className="px-5 py-4 text-sm text-muted">No models.</li>}
      </ul>
    </div>
  );
}
