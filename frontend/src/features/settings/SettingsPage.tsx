import { Check, Copy, KeyRound, Plus, ScrollText, Trash2, Users, Layers } from "lucide-react";
import { useState, type FormEvent } from "react";

import { errorMessage } from "../../api/client";
import {
  useAddMember,
  useApiKeys,
  useAudit,
  useCreateApiKey,
  useCreateWorkspace,
  useMembers,
  useRemoveMember,
  useRevokeApiKey,
  useUpdateMember,
} from "../../api/queries";
import type { ApiKeyCreated, Role } from "../../api/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Field, Input, Select } from "../../components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { cn } from "../../lib/cn";
import { relativeTime } from "../../lib/format";
import { roleAtLeast, useAuth } from "../auth/auth-context";

type Tab = "members" | "keys" | "workspaces" | "audit";
const ROLES: Role[] = ["viewer", "editor", "admin", "owner"];

export function SettingsPage() {
  const { role } = useAuth();
  const isAdmin = roleAtLeast(role, "admin");
  const tabs: Array<{ id: Tab; label: string; icon: typeof Users; show: boolean }> = [
    { id: "members", label: "Members", icon: Users, show: true },
    { id: "keys", label: "API keys", icon: KeyRound, show: roleAtLeast(role, "editor") },
    { id: "workspaces", label: "Workspaces", icon: Layers, show: true },
    { id: "audit", label: "Audit log", icon: ScrollText, show: isAdmin },
  ];
  const visible = tabs.filter((t) => t.show);
  const [tab, setTab] = useState<Tab>("members");

  return (
    <>
      <PageHeader title="Organization" description="Members, roles, API keys and the audit trail of your organization." />
      <div role="tablist" aria-label="Settings sections" className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
        {visible.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            onClick={() => setTab(id)}
            className={cn(
              "-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
              tab === id ? "border-brand-500 text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "members" && <MembersPanel canManage={isAdmin} />}
        {tab === "keys" && <ApiKeysPanel />}
        {tab === "workspaces" && <WorkspacesPanel canCreate={isAdmin} />}
        {tab === "audit" && isAdmin && <AuditPanel />}
      </div>
    </>
  );
}

function MembersPanel({ canManage }: { canManage: boolean }) {
  const { me, role } = useAuth();
  const toast = useToast();
  const members = useMembers();
  const add = useAddMember();
  const update = useUpdateMember();
  const remove = useRemoveMember();
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<Role>("editor");
  const [toRemove, setToRemove] = useState<{ id: string; email: string } | null>(null);
  const grantable = ROLES.filter((r) => roleAtLeast(role, r));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate(
      { email, role: newRole },
      {
        onSuccess: () => {
          setEmail("");
          toast.push({ title: "Member added" });
        },
        onError: (error) => toast.push({ tone: "error", title: "Could not add member", description: errorMessage(error) }),
      },
    );
  };

  return (
    <div className="space-y-6">
      {canManage && (
        <Card className="p-5">
          <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Field label="Add an existing user by email" className="flex-1">
              {(p) => <Input {...p} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" />}
            </Field>
            <Field label="Role" className="sm:w-40">
              {(p) => (
                <Select {...p} value={newRole} onChange={(e) => setNewRole(e.target.value as Role)}>
                  {grantable.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Button type="submit" variant="primary" icon={<Plus className="size-4" />} loading={add.isPending} disabled={!email}>
              Add
            </Button>
          </form>
        </Card>
      )}
      <Card>
        {members.isPending ? (
          <div className="space-y-3 p-5" aria-busy="true">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-5 w-1/3" />
          </div>
        ) : members.isError ? (
          <div className="p-5">
            <ErrorState message={errorMessage(members.error)} onRetry={() => void members.refetch()} />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {members.data.map((m) => {
              const self = m.user_id === me?.user.id;
              const editable = canManage && !self && roleAtLeast(role, m.role);
              return (
                <li key={m.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {m.name || m.email} {self && <span className="text-subtle">(you)</span>}
                    </span>
                    <span className="block truncate text-xs text-muted">{m.email}</span>
                  </span>
                  {editable ? (
                    <Select
                      aria-label={`Role of ${m.email}`}
                      className="w-32"
                      value={m.role}
                      onChange={(e) =>
                        update.mutate(
                          { userId: m.user_id, role: e.target.value as Role },
                          { onError: (error) => toast.push({ tone: "error", title: "Could not change role", description: errorMessage(error) }) },
                        )
                      }
                    >
                      {grantable.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Badge tone={m.role === "owner" ? "brand" : "neutral"}>{m.role}</Badge>
                  )}
                  {editable && (
                    <Button size="sm" variant="ghost" aria-label={`Remove ${m.email}`} icon={<Trash2 className="size-4" />} onClick={() => setToRemove({ id: m.user_id, email: m.email })} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <ConfirmDialog
        open={!!toRemove}
        title="Remove member?"
        message={`${toRemove?.email} will lose access to every workspace of this organization.`}
        confirmLabel="Remove"
        onCancel={() => setToRemove(null)}
        onConfirm={() => {
          if (!toRemove) return;
          remove.mutate(toRemove.id, {
            onSettled: () => setToRemove(null),
            onError: (error) => toast.push({ tone: "error", title: "Could not remove member", description: errorMessage(error) }),
          });
        }}
      />
    </div>
  );
}

function ApiKeysPanel() {
  const { role } = useAuth();
  const toast = useToast();
  const keysQuery = useApiKeys();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const [name, setName] = useState("");
  const [keyRole, setKeyRole] = useState<Exclude<Role, "owner">>("editor");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const roles = (["viewer", "editor", "admin"] as const).filter((r) => roleAtLeast(role, r));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { name, role: keyRole, expiresInDays: null },
      {
        onSuccess: (key) => {
          setCreated(key);
          setCopied(false);
          setName("");
        },
        onError: (error) => toast.push({ tone: "error", title: "Could not create key", description: errorMessage(error) }),
      },
    );
  };

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Field label="Key name" className="flex-1">
            {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="CI pipeline" />}
          </Field>
          <Field label="Role" className="sm:w-40">
            {(p) => (
              <Select {...p} value={keyRole} onChange={(e) => setKeyRole(e.target.value as Exclude<Role, "owner">)}>
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" icon={<Plus className="size-4" />} loading={create.isPending} disabled={!name}>
            Create key
          </Button>
        </form>
        {created && (
          <div role="status" className="mt-4 rounded-xl border border-success/25 bg-success/10 p-4">
            <p className="text-sm font-medium">Copy your new key now — it will not be shown again.</p>
            <div className="mt-2 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-lg bg-surface px-3 py-2 font-mono text-xs" data-testid="new-api-key">
                {created.token}
              </code>
              <Button
                size="sm"
                icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                onClick={() => {
                  void navigator.clipboard?.writeText(created.token);
                  setCopied(true);
                }}
              >
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>
        )}
      </Card>
      <Card>
        {keysQuery.isPending ? (
          <div className="p-5" aria-busy="true">
            <Skeleton className="h-5 w-1/2" />
          </div>
        ) : keysQuery.isError ? (
          <div className="p-5">
            <ErrorState message={errorMessage(keysQuery.error)} onRetry={() => void keysQuery.refetch()} />
          </div>
        ) : keysQuery.data.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={<KeyRound />} title="No API keys" description="Keys let scripts and other apps call the API on behalf of this workspace." />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {keysQuery.data.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{k.name}</span>
                  <span className="block font-mono text-xs text-muted">eaa_{k.prefix}_…</span>
                </span>
                <Badge>{k.role}</Badge>
                <span className="text-xs text-subtle">{k.last_used_at ? `used ${relativeTime(k.last_used_at)}` : "never used"}</span>
                {k.revoked_at ? (
                  <Badge tone="danger">revoked</Badge>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => revoke.mutate(k.id)} aria-label={`Revoke ${k.name}`}>
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function WorkspacesPanel({ canCreate }: { canCreate: boolean }) {
  const { me, workspace, switchWorkspace, reload } = useAuth();
  const toast = useToast();
  const create = useCreateWorkspace();
  const [name, setName] = useState("");
  const org = me?.organizations.find((o) => o.workspaces.some((w) => w.id === workspace?.id));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(name, {
      onSuccess: async () => {
        setName("");
        await reload();
        toast.push({ title: "Workspace created" });
      },
      onError: (error) => toast.push({ tone: "error", title: "Could not create workspace", description: errorMessage(error) }),
    });
  };

  return (
    <div className="space-y-6">
      {canCreate && (
        <Card className="p-5">
          <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Field label="New workspace" hint="Workspaces separate agents, conversations and files." className="flex-1">
              {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="Research" />}
            </Field>
            <Button type="submit" variant="primary" icon={<Plus className="size-4" />} loading={create.isPending} disabled={!name}>
              Create
            </Button>
          </form>
        </Card>
      )}
      <Card>
        <ul className="divide-y divide-line">
          {(org?.workspaces ?? []).map((w) => (
            <li key={w.id} className="flex items-center gap-3 px-5 py-3.5">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{w.name}</span>
                <span className="block font-mono text-xs text-muted">files: workspace/{w.slug}/</span>
              </span>
              {w.id === workspace?.id ? (
                <Badge tone="brand">current</Badge>
              ) : (
                <Button size="sm" onClick={() => void switchWorkspace(w.id)}>
                  Switch
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function AuditPanel() {
  const audit = useAudit();
  if (audit.isPending)
    return (
      <Card className="space-y-3 p-5" aria-busy="true">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </Card>
    );
  if (audit.isError) return <ErrorState message={errorMessage(audit.error)} onRetry={() => void audit.refetch()} />;
  return (
    <Card>
      <ul className="divide-y divide-line">
        {audit.data.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
            <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs">{e.action}</code>
            <span className="min-w-0 flex-1 truncate text-muted">
              {e.target_type ? `${e.target_type} ${e.target_id?.slice(0, 8) ?? ""}` : ""}
              {Object.keys(e.meta).length > 0 && ` · ${Object.entries(e.meta).map(([k, v]) => `${k}=${String(v)}`).join(", ")}`}
            </span>
            <time className="text-xs text-subtle" dateTime={e.created_at}>
              {relativeTime(e.created_at)}
            </time>
          </li>
        ))}
      </ul>
    </Card>
  );
}
