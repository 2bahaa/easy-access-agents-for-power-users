import { AlertCircle, Save } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import type { SkillWrite } from "../api/types";
import { slugify } from "../lib/format";
import { validateSkill, type SkillFormErrors } from "../lib/skillForm";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Field, Input, Textarea } from "./ui/Field";

export interface SkillEditorProps {
  initialValues: SkillWrite;
  isNew?: boolean;
  isBuiltin?: boolean;
  onSubmit: (values: SkillWrite) => void;
  submitting?: boolean;
  serverError?: string | null;
  secondaryActions?: ReactNode;
}

/** Edit a Markdown skill: name, slug, description and instruction content. */
export function SkillEditor({
  initialValues,
  isNew,
  isBuiltin,
  onSubmit,
  submitting,
  serverError,
  secondaryActions,
}: SkillEditorProps) {
  const [values, setValues] = useState<SkillWrite>(initialValues);
  const [slugTouched, setSlugTouched] = useState(!isNew);
  const [errors, setErrors] = useState<SkillFormErrors>({});
  const dirty = JSON.stringify(values) !== JSON.stringify(initialValues);

  const [tagInput, setTagInput] = useState((initialValues.tags ?? []).join(", "));
  const setTags = (raw: string) => {
    setTagInput(raw);
    const tags = [...new Set(raw.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean))];
    setValues((v) => ({ ...v, tags }));
  };

  const set = (key: keyof SkillWrite, value: string) =>
    setValues((v) => ({
      ...v,
      [key]: value,
      ...(key === "name" && !slugTouched ? { slug: slugify(value) } : {}),
    }));

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const found = validateSkill(values);
    setErrors(found);
    if (Object.keys(found).length === 0) onSubmit({ ...values, name: values.name.trim() });
  };

  return (
    <form onSubmit={handleSubmit} noValidate aria-label="Skill editor" className="flex h-full flex-col">
      <div className="flex-1 space-y-4 p-5 sm:p-6">
        {isBuiltin && (
          <Badge tone="brand" className="mb-1">
            Built-in skill · your edits are kept across restarts
          </Badge>
        )}
        {serverError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/5 p-3 text-sm text-red-700 dark:text-red-300"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            {serverError}
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" required error={errors.name}>
            {(a11y) => (
              <Input
                {...a11y}
                value={values.name}
                maxLength={100}
                placeholder="Concise answers"
                onChange={(e) => set("name", e.target.value)}
              />
            )}
          </Field>
          <Field label="Slug" required error={errors.slug} hint="Unique identifier.">
            {(a11y) => (
              <Input
                {...a11y}
                value={values.slug}
                maxLength={100}
                placeholder="concise-answers"
                onChange={(e) => {
                  setSlugTouched(true);
                  set("slug", e.target.value);
                }}
                className="font-mono text-[13px]"
              />
            )}
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Category" hint="Groups skills in the library.">
            {(a11y) => (
              <Input
                {...a11y}
                value={values.category ?? "general"}
                maxLength={50}
                onChange={(e) => set("category", e.target.value)}
              />
            )}
          </Field>
          <Field label="Tags" hint="Comma-separated, e.g. writing, tone">
            {(a11y) => <Input {...a11y} value={tagInput} onChange={(e) => setTags(e.target.value)} />}
          </Field>
        </div>
        <Field label="Description" error={errors.description} hint="Shown when picking skills.">
          {(a11y) => (
            <Input
              {...a11y}
              value={values.description}
              maxLength={500}
              placeholder="Keep replies short, direct and free of filler."
              onChange={(e) => set("description", e.target.value)}
            />
          )}
        </Field>
        <Field
          label="Instructions (Markdown)"
          required
          error={errors.content_md}
          trailing={
            <span className="text-xs text-subtle tabular-nums">
              {values.content_md.length.toLocaleString()} chars
            </span>
          }
        >
          {(a11y) => (
            <Textarea
              {...a11y}
              rows={16}
              value={values.content_md}
              placeholder={"# Concise answers\n\n- Answer directly in the first sentence.\n- Prefer short bullet lists."}
              onChange={(e) => set("content_md", e.target.value)}
              className="font-mono text-[13px]"
            />
          )}
        </Field>
      </div>
      <div className="flex items-center gap-2 border-t border-line px-5 py-3 sm:px-6">
        <p className="flex-1 text-sm text-muted">
          {dirty ? (
            <span className="flex items-center gap-2">
              <span className="size-2 rounded-full bg-amber-500" /> Unsaved changes
            </span>
          ) : isNew ? (
            "New skill"
          ) : (
            <span className="text-subtle">All changes saved</span>
          )}
        </p>
        {secondaryActions}
        <Button type="submit" variant="primary" loading={submitting} icon={<Save className="size-4" />}>
          {isNew ? "Create skill" : "Save"}
        </Button>
      </div>
    </form>
  );
}
