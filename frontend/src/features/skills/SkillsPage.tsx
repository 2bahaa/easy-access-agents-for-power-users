import { BookOpen, MousePointerClick, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router";

import { errorMessage } from "../../api/client";
import { useDeleteSkill, useSaveSkill, useSkill, useSkills } from "../../api/queries";
import type { SkillWrite } from "../../api/types";
import { SkillEditor } from "../../components/SkillEditor";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Input } from "../../components/ui/Field";
import { LinkButton } from "../../components/ui/LinkButton";
import { EmptyState, ErrorState, Skeleton } from "../../components/ui/States";
import { useToast } from "../../components/ui/toast-context";
import { PageHeader } from "../../layout/PageHeader";
import { cn } from "../../lib/cn";

const EMPTY_SKILL: SkillWrite = { slug: "", name: "", description: "", content_md: "" };

export function SkillsPage() {
  const { skillId } = useParams();
  const isNew = skillId === "new";
  const selectedId = isNew ? undefined : skillId;
  const { data: skills, isPending, isError, error, refetch } = useSkills();
  const [query, setQuery] = useState("");

  const filtered = (skills ?? []).filter((s) =>
    `${s.name} ${s.slug} ${s.description}`.toLowerCase().includes(query.toLowerCase()),
  );
  const editorOpen = isNew || !!selectedId;

  return (
    <>
      <PageHeader
        title="Skills"
        description="Reusable Markdown instructions you can attach to any agent."
        actions={
          <LinkButton to="/skills/new" variant="primary" icon={<Plus className="size-4" />}>
            New skill
          </LinkButton>
        }
      />

      {isError && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}

      {skills && skills.length === 0 && !isNew ? (
        <EmptyState
          icon={<BookOpen />}
          title="No skills yet"
          description="Write instructions once — a tone, a procedure, a format — and reuse them across agents."
          action={
            <LinkButton to="/skills/new" variant="primary" icon={<Plus className="size-4" />}>
              New skill
            </LinkButton>
          }
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <Card className={cn("flex flex-col overflow-hidden", editorOpen && "hidden lg:flex")}>
            <div className="border-b border-line p-3">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
                <Input
                  aria-label="Search skills"
                  placeholder="Search…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-9 pl-9"
                />
              </div>
            </div>
            <ul aria-label="Skills" className="scrollbar-thin max-h-[65vh] flex-1 space-y-0.5 overflow-y-auto p-2">
              {isPending &&
                [0, 1, 2].map((i) => (
                  <li key={i} className="space-y-2 p-3">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-3 w-full" />
                  </li>
                ))}
              {filtered.map((skill) => (
                <li key={skill.id}>
                  <NavLink
                    to={`/skills/${skill.id}`}
                    className={({ isActive }) =>
                      cn(
                        "block rounded-xl px-3 py-2.5 transition-colors",
                        isActive ? "bg-brand-500/10" : "hover:bg-surface-2",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span className="flex items-center gap-2">
                          <span
                            className={cn(
                              "truncate text-sm font-medium",
                              isActive && "text-brand-700 dark:text-brand-400",
                            )}
                          >
                            {skill.name}
                          </span>
                          {skill.is_builtin && <Badge>Built-in</Badge>}
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-[11px] text-subtle">
                          {skill.slug}
                        </span>
                        {skill.description && (
                          <span className="mt-1 line-clamp-2 block text-xs text-muted">
                            {skill.description}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
              {skills && filtered.length === 0 && (
                <li className="p-4 text-center text-sm text-muted">No matching skills.</li>
              )}
            </ul>
          </Card>

          <Card className={cn("min-h-[420px] overflow-hidden", !editorOpen && "hidden lg:block")}>
            {isNew ? (
              <SkillEditorPanel key="new" />
            ) : selectedId ? (
              <SkillEditorPanel key={selectedId} skillId={selectedId} />
            ) : (
              <div className="grid h-full min-h-[420px] place-items-center p-8 text-center">
                <div>
                  <MousePointerClick className="mx-auto mb-3 size-6 text-subtle" />
                  <p className="font-medium">Select a skill to edit</p>
                  <p className="mt-1 text-sm text-muted">or create a new one.</p>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </>
  );
}

function SkillEditorPanel({ skillId }: { skillId?: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const skill = useSkill(skillId);
  const save = useSaveSkill();
  const remove = useDeleteSkill();
  const [confirm, setConfirm] = useState(false);

  if (skillId && skill.isPending) {
    return (
      <div className="space-y-4 p-6" aria-busy="true">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (skillId && skill.isError) {
    return (
      <div className="p-6">
        <ErrorState title="Could not load skill" message={errorMessage(skill.error)} />
      </div>
    );
  }

  const data = skill.data;
  const initial: SkillWrite = data
    ? { slug: data.slug, name: data.name, description: data.description, content_md: data.content_md }
    : EMPTY_SKILL;

  return (
    <>
      <SkillEditor
        key={data?.updated_at ?? "new"}
        initialValues={initial}
        isNew={!skillId}
        isBuiltin={data?.is_builtin}
        submitting={save.isPending}
        serverError={save.isError ? errorMessage(save.error) : null}
        onSubmit={(values) =>
          save.mutate(
            { id: skillId, data: values },
            {
              onSuccess: (saved) => {
                toast.push({ title: skillId ? "Skill saved" : "Skill created", description: saved.name });
                if (!skillId) navigate(`/skills/${saved.id}`, { replace: true });
              },
            },
          )
        }
        secondaryActions={
          skillId && (
            <Button
              variant="ghost"
              icon={<Trash2 className="size-4" />}
              onClick={() => setConfirm(true)}
              className="hover:text-red-600"
            >
              Delete
            </Button>
          )
        }
      />
      <ConfirmDialog
        open={confirm}
        title="Delete this skill?"
        message="It will be detached from every agent that uses it."
        loading={remove.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() =>
          skillId &&
          remove.mutate(skillId, {
            onSuccess: () => {
              toast.push({ title: "Skill deleted" });
              navigate("/skills", { replace: true });
            },
            onError: (err) => {
              setConfirm(false);
              toast.push({ tone: "error", title: "Could not delete skill", description: errorMessage(err) });
            },
          })
        }
      />
    </>
  );
}
