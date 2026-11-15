import { Globe, Plus, RefreshCw, Server, Trash2, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { errorMessage } from "../../api/client";
import {
  useCreateCustomTool,
  useCreateMcpServer,
  useCustomTools,
  useDeleteCustomTool,
  useDeleteMcpServer,
  useMcpServers,
  useRefreshMcpServer,
  useToggleMcpTool,
} from "../../api/queries";
import type { HttpParam, McpServer } from "../../api/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Field, Input, Select } from "../../components/ui/Field";
import { Switch } from "../../components/ui/Switch";
import { EmptyState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { relativeTime } from "../../lib/format";

type Pair = { key: string; value: string };

/** Write-only key/value secrets (env vars or headers). */
function SecretPairs({ label, pairs, onChange }: { label: string; pairs: Pair[]; onChange: (p: Pair[]) => void }) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      {pairs.map((p, i) => (
        <div key={i} className="flex gap-2">
          <Input aria-label={`${label} name ${i + 1}`} placeholder="NAME" value={p.key} onChange={(e) => onChange(pairs.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
          <Input aria-label={`${label} value ${i + 1}`} type="password" autoComplete="off" placeholder="value (stored encrypted)" value={p.value} onChange={(e) => onChange(pairs.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
          <Button size="sm" variant="ghost" aria-label={`Remove ${label} ${i + 1}`} icon={<X className="size-4" />} onClick={() => onChange(pairs.filter((_, j) => j !== i))} />
        </div>
      ))}
      <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => onChange([...pairs, { key: "", value: "" }])}>
        Add
      </Button>
    </fieldset>
  );
}

const toRecord = (pairs: Pair[]) => Object.fromEntries(pairs.filter((p) => p.key.trim()).map((p) => [p.key.trim(), p.value]));

function StatusBadge({ status }: { status: string }) {
  if (status === "ok") return <Badge tone="success">Connected</Badge>;
  if (status === "error") return <Badge tone="danger">Error</Badge>;
  return <Badge>Not checked</Badge>;
}

export function McpServersSection({ canManage }: { canManage: boolean }) {
  const servers = useMcpServers();
  const [adding, setAdding] = useState(false);
  return (
    <section aria-labelledby="mcp-heading" className="mt-10">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 id="mcp-heading" className="text-lg font-semibold tracking-tight">MCP servers</h2>
          <p className="text-sm text-muted">Tools from Model Context Protocol servers. Discovered tools start disabled.</p>
        </div>
        {canManage && !adding && (
          <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
            Add MCP server
          </Button>
        )}
      </div>
      {adding && <AddMcpServer onDone={() => setAdding(false)} />}
      {servers.isPending ? (
        <Skeleton className="h-24 rounded-2xl" />
      ) : servers.isError ? (
        <p className="text-sm text-danger">{errorMessage(servers.error)}</p>
      ) : servers.data.length === 0 ? (
        <EmptyState icon={<Server />} title="No MCP servers" description="Connect a server to give agents its tools." />
      ) : (
        <div className="space-y-3">
          {servers.data.map((s) => (
            <McpServerCard key={s.id} server={s} canManage={canManage} />
          ))}
        </div>
      )}
    </section>
  );
}

function AddMcpServer({ onDone }: { onDone: () => void }) {
  const create = useCreateMcpServer();
  const toast = useToast();
  const [transport, setTransport] = useState<"stdio" | "http">("http");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [secrets, setSecrets] = useState<Pair[]>([]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const secretRecord = toRecord(secrets);
    create.mutate(
      {
        name,
        slug,
        transport,
        command: transport === "stdio" ? command : null,
        args: transport === "stdio" ? args.split(" ").filter(Boolean) : [],
        url: transport === "http" ? url : null,
        env: transport === "stdio" ? secretRecord : {},
        headers: transport === "http" ? secretRecord : {},
      },
      {
        onSuccess: (s) => {
          toast.push({ title: "MCP server added", description: "Refresh it to discover its tools." });
          onDone();
          void s;
        },
      },
    );
  };

  return (
    <Card className="mb-4 p-5">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" aria-label="Add MCP server">
        <Field label="Transport">
          {(p) => (
            <Select {...p} value={transport} onChange={(e) => setTransport(e.target.value as "stdio" | "http")}>
              <option value="http">Streamable HTTP</option>
              <option value="stdio">Local command (stdio)</option>
            </Select>
          )}
        </Field>
        <Field label="Name">{(p) => <Input {...p} value={name} onChange={(e) => { setName(e.target.value); setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 31)); }} />}</Field>
        <Field label="Slug" hint="Used in tool names: mcp__<slug>__<tool>">{(p) => <Input {...p} value={slug} onChange={(e) => setSlug(e.target.value)} />}</Field>
        {transport === "http" ? (
          <Field label="URL" hint="e.g. http://127.0.0.1:8080/mcp">{(p) => <Input {...p} value={url} onChange={(e) => setUrl(e.target.value)} />}</Field>
        ) : (
          <>
            <Field label="Command" hint="Must be on the server's allow-list (MCP_STDIO_ALLOWED_COMMANDS).">{(p) => <Input {...p} value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" />}</Field>
            <Field label="Arguments" hint="Space-separated">{(p) => <Input {...p} value={args} onChange={(e) => setArgs(e.target.value)} placeholder="-y @modelcontextprotocol/server-everything" />}</Field>
          </>
        )}
        <div className="sm:col-span-2">
          <SecretPairs label={transport === "http" ? "Headers" : "Environment variables"} pairs={secrets} onChange={setSecrets} />
        </div>
        {create.isError && <p role="alert" className="text-sm text-danger sm:col-span-2">{errorMessage(create.error)}</p>}
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!name || !slug || (transport === "http" ? !url : !command)}>
            Save server
          </Button>
          <Button onClick={onDone}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}

function McpServerCard({ server: s, canManage }: { server: McpServer; canManage: boolean }) {
  const toast = useToast();
  const refresh = useRefreshMcpServer();
  const toggle = useToggleMcpTool();
  const remove = useDeleteMcpServer();
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 px-5 py-4">
        <Server className="size-4 text-subtle" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{s.name}</span>
          <span className="block truncate font-mono text-xs text-muted">
            {s.transport === "http" ? s.url : `${s.command} ${s.args.join(" ")}`}
            {s.secret_keys.length > 0 && ` · secrets: ${s.secret_keys.join(", ")}`}
            {s.last_checked_at && ` · checked ${relativeTime(s.last_checked_at)}`}
          </span>
        </span>
        <StatusBadge status={s.status} />
        {canManage && (
          <>
            <Button
              size="sm"
              icon={<RefreshCw className="size-3.5" />}
              loading={refresh.isPending}
              onClick={() =>
                refresh.mutate(s.id, {
                  onSuccess: (r) =>
                    r.server.status === "ok"
                      ? toast.push({ title: `Found ${r.server.tools.length} tools`, description: r.warnings.join(" ") || undefined })
                      : toast.push({ tone: "error", title: "Could not reach the server", description: r.server.last_error ?? undefined }),
                })
              }
            >
              Discover tools
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Delete ${s.name}`}
              icon={<Trash2 className="size-4" />}
              onClick={() => remove.mutate(s.id, { onError: (error) => toast.push({ tone: "error", title: "Could not delete", description: errorMessage(error) }) })}
            />
          </>
        )}
      </div>
      {s.status === "error" && s.last_error && <p className="px-5 pb-3 text-xs text-danger">{s.last_error}</p>}
      {s.tools.length > 0 && (
        <ul className="divide-y divide-line border-t border-line" aria-label={`Tools of ${s.name}`}>
          {s.tools.map((t) => (
            <li key={t.name} className="flex items-start gap-3 px-5 py-3">
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[13px]">mcp__{s.slug}__{t.name}</span>
                <span className="block text-xs text-muted">{t.description || "No description"}</span>
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-subtle">Input schema</summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2">{JSON.stringify(t.input_schema, null, 2)}</pre>
                </details>
              </span>
              <Switch
                checked={t.enabled}
                disabled={!canManage}
                label={`Enable ${t.name}`}
                onChange={(enabled) => toggle.mutate({ id: s.id, tool: t.name, enabled })}
              />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const EMPTY_PARAM: HttpParam = { name: "", type: "string", location: "query", required: true, description: "" };

export function CustomToolsSection({ canManage }: { canManage: boolean }) {
  const tools = useCustomTools();
  const remove = useDeleteCustomTool();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  return (
    <section aria-labelledby="http-heading" className="mt-10">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 id="http-heading" className="text-lg font-semibold tracking-tight">Custom HTTP tools</h2>
          <p className="text-sm text-muted">Call an API on an allow-listed host with validated parameters.</p>
        </div>
        {canManage && !adding && (
          <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
            Add HTTP tool
          </Button>
        )}
      </div>
      {adding && <AddCustomTool onDone={() => setAdding(false)} />}
      {tools.isPending ? (
        <Skeleton className="h-20 rounded-2xl" />
      ) : tools.isError ? (
        <p className="text-sm text-danger">{errorMessage(tools.error)}</p>
      ) : tools.data.length === 0 ? (
        <EmptyState icon={<Globe />} title="No HTTP tools" description="Define one to let agents call an approved API." />
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {tools.data.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-[13px]">{t.tool_name}</span>
                  <span className="block truncate text-xs text-muted">
                    {t.method} {t.url_template} · {t.params.length} params
                    {t.header_keys.length > 0 && ` · headers: ${t.header_keys.join(", ")}`}
                  </span>
                </span>
                {canManage && (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Delete ${t.tool_name}`}
                    icon={<Trash2 className="size-4" />}
                    onClick={() => remove.mutate(t.id, { onError: (error) => toast.push({ tone: "error", title: "Could not delete", description: errorMessage(error) }) })}
                  />
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}

function AddCustomTool({ onDone }: { onDone: () => void }) {
  const create = useCreateCustomTool();
  const toast = useToast();
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [method, setMethod] = useState<"GET" | "POST">("GET");
  const [url, setUrl] = useState("https://");
  const [params, setParams] = useState<HttpParam[]>([]);
  const [headers, setHeaders] = useState<Pair[]>([]);
  const setParam = (i: number, patch: Partial<HttpParam>) => setParams(params.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { slug, description, method, url_template: url, params, headers: toRecord(headers) },
      {
        onSuccess: (t) => {
          toast.push({ title: "HTTP tool created", description: t.tool_name });
          onDone();
        },
      },
    );
  };

  return (
    <Card className="mb-4 p-5">
      <form onSubmit={submit} className="space-y-4" aria-label="Add HTTP tool">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Slug" hint="Tool name: http__<slug>">{(p) => <Input {...p} value={slug} onChange={(e) => setSlug(e.target.value)} />}</Field>
          <Field label="Method">
            {(p) => (
              <Select {...p} value={method} onChange={(e) => setMethod(e.target.value as "GET" | "POST")}>
                <option>GET</option>
                <option>POST</option>
              </Select>
            )}
          </Field>
          <Field label="URL" hint="Use {name} for path parameters">{(p) => <Input {...p} value={url} onChange={(e) => setUrl(e.target.value)} />}</Field>
        </div>
        <Field label="Description" hint="Tell the model when to use it.">{(p) => <Input {...p} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Parameters</legend>
          {params.map((p, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[1fr_120px_120px_auto_auto]">
              <Input aria-label={`Parameter ${i + 1} name`} placeholder="name" value={p.name} onChange={(e) => setParam(i, { name: e.target.value })} />
              <Select aria-label={`Parameter ${i + 1} type`} value={p.type} onChange={(e) => setParam(i, { type: e.target.value as HttpParam["type"] })}>
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="integer">integer</option>
                <option value="boolean">boolean</option>
              </Select>
              <Select aria-label={`Parameter ${i + 1} location`} value={p.location} onChange={(e) => setParam(i, { location: e.target.value as HttpParam["location"] })}>
                <option value="query">query</option>
                <option value="path">path</option>
                <option value="body">body</option>
              </Select>
              <label className="flex items-center gap-1.5 text-xs">
                <input type="checkbox" checked={p.required} onChange={(e) => setParam(i, { required: e.target.checked })} /> required
              </label>
              <Button size="sm" variant="ghost" aria-label={`Remove parameter ${i + 1}`} icon={<X className="size-4" />} onClick={() => setParams(params.filter((_, j) => j !== i))} />
            </div>
          ))}
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setParams([...params, { ...EMPTY_PARAM }])}>
            Add parameter
          </Button>
        </fieldset>
        <SecretPairs label="Headers" pairs={headers} onChange={setHeaders} />
        {create.isError && <p role="alert" className="text-sm text-danger">{errorMessage(create.error)}</p>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!slug || !description || url.length < 9}>
            Save tool
          </Button>
          <Button onClick={onDone}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
