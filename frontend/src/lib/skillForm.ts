import type { SkillWrite } from "../api/types";

export const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const CONTENT_MAX = 50_000;

export type SkillFormErrors = Partial<Record<keyof SkillWrite, string>>;

export function validateSkill(values: SkillWrite): SkillFormErrors {
  const errors: SkillFormErrors = {};
  if (!values.name.trim()) errors.name = "Give the skill a name.";
  if (!values.slug) errors.slug = "A slug is required.";
  else if (!SLUG_RE.test(values.slug))
    errors.slug = "Use lowercase letters, numbers and single hyphens (e.g. concise-answers).";
  if (values.description.length > 500) errors.description = "Keep it under 500 characters.";
  if (!values.content_md.trim()) errors.content_md = "Write the instructions this skill adds.";
  else if (values.content_md.length > CONTENT_MAX)
    errors.content_md = `Limited to ${CONTENT_MAX.toLocaleString()} characters.`;
  return errors;
}
