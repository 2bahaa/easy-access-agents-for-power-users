import { ArrowDown, ArrowUp, BookOpen, Plus, Search, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import type { SkillSummary } from "../api/types";
import { Badge } from "./ui/Badge";
import { Input } from "./ui/Field";

export interface SkillSelectorProps {
  skills: SkillSummary[];
  /** Attached skill ids, in prompt order. */
  value: string[];
  onChange: (ids: string[]) => void;
  /** Rendered when the library is empty (e.g. a link to create a skill). */
  emptyAction?: ReactNode;
}

function move<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}

/** Attach skills to an agent and order them (order = order in the system prompt). */
export function SkillSelector({ skills, value, onChange, emptyAction }: SkillSelectorProps) {
  const [query, setQuery] = useState("");
  const byId = useMemo(() => new Map(skills.map((s) => [s.id, s])), [skills]);
  const attached = value.map((id) => byId.get(id)).filter((s): s is SkillSummary => !!s);
  const available = skills.filter(
    (s) =>
      !value.includes(s.id) &&
      `${s.name} ${s.slug} ${s.description}`.toLowerCase().includes(query.toLowerCase()),
  );

  if (skills.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-line-strong p-5 text-center text-sm text-muted">
        <BookOpen className="mx-auto mb-2 size-5 text-subtle" />
        Your skill library is empty.
        {emptyAction && <div className="mt-3">{emptyAction}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-xs font-medium tracking-wide text-subtle uppercase">
          Attached · {attached.length}
        </p>
        {attached.length === 0 ? (
          <p className="rounded-xl bg-surface-2 px-3 py-2.5 text-sm text-muted">
            No skills attached. Skills add reusable instructions to the system prompt.
          </p>
        ) : (
          <ol aria-label="Attached skills" className="space-y-1.5">
            {attached.map((skill, index) => (
              <li
                key={skill.id}
                className="flex items-center gap-2 rounded-xl border border-brand-500/25 bg-brand-500/5 py-2 pr-1.5 pl-3"
              >
                <span className="grid size-5 shrink-0 place-items-center rounded-md bg-brand-500/15 text-[11px] font-semibold text-brand-600 dark:text-brand-400">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{skill.name}</span>
                <IconButton
                  label={`Move ${skill.name} up`}
                  disabled={index === 0}
                  onClick={() => onChange(move(value, index, index - 1))}
                >
                  <ArrowUp />
                </IconButton>
                <IconButton
                  label={`Move ${skill.name} down`}
                  disabled={index === attached.length - 1}
                  onClick={() => onChange(move(value, index, index + 1))}
                >
                  <ArrowDown />
                </IconButton>
                <IconButton
                  label={`Remove ${skill.name}`}
                  onClick={() => onChange(value.filter((id) => id !== skill.id))}
                >
                  <X />
                </IconButton>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div>
        <p className="mb-2 text-xs font-medium tracking-wide text-subtle uppercase">Library</p>
        <div className="relative mb-2">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
          <Input
            aria-label="Search skills"
            placeholder="Search skills…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <ul aria-label="Available skills" className="scrollbar-thin max-h-56 space-y-1 overflow-y-auto">
          {available.length === 0 && (
            <li className="px-3 py-2 text-sm text-subtle">
              {query ? "No matching skills." : "All skills are attached."}
            </li>
          )}
          {available.map((skill) => (
            <li key={skill.id}>
              <button
                type="button"
                onClick={() => onChange([...value, skill.id])}
                aria-label={`Attach ${skill.name}`}
                className="group flex w-full items-start gap-3 rounded-xl px-3 py-2 text-left transition-colors hover:bg-surface-2"
              >
                <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border border-line-strong text-subtle transition-colors group-hover:border-brand-500 group-hover:bg-brand-500 group-hover:text-white">
                  <Plus className="size-3" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-sm font-medium">
                    {skill.name}
                    {skill.is_builtin && <Badge>Built-in</Badge>}
                  </span>
                  {skill.description && (
                    <span className="mt-0.5 line-clamp-1 block text-xs text-muted">
                      {skill.description}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-fg disabled:opacity-30 disabled:hover:bg-transparent [&_svg]:size-3.5"
    >
      {children}
    </button>
  );
}
