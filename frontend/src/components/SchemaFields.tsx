import type { JsonSchema } from "../api/types";
import { Field, Input } from "./ui/Field";
import { Switch } from "./ui/Switch";

function placeholderFor(prop: JsonSchema): string | undefined {
  if (prop.examples?.length) return `e.g. ${String(prop.examples[0])}`;
  if (prop.default !== undefined && prop.default !== "") return String(prop.default);
  return undefined;
}

/**
 * Renders inputs for a flat object JSON schema (string / number / integer / boolean).
 * Used for per-agent tool configuration generated from the backend's Pydantic models.
 */
export function SchemaFields({
  schema,
  value,
  onChange,
  idPrefix,
}: {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  idPrefix: string;
}) {
  const entries = Object.entries(schema.properties ?? {});
  return (
    <div className="space-y-3">
      {entries.map(([key, prop]) => {
        const label = prop.title ?? key;
        const set = (v: unknown) => onChange({ ...value, [key]: v });
        if (prop.type === "boolean") {
          return (
            <div key={key} className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">{label}</p>
                {prop.description && <p className="text-xs text-muted">{prop.description}</p>}
              </div>
              <Switch
                id={`${idPrefix}-${key}`}
                label={label}
                checked={Boolean(value[key])}
                onChange={set}
              />
            </div>
          );
        }
        const numeric = prop.type === "integer" || prop.type === "number";
        return (
          <Field key={key} label={label} hint={prop.description}>
            {(a11y) => (
              <Input
                {...a11y}
                type={numeric ? "number" : "text"}
                value={value[key] === undefined || value[key] === null ? "" : String(value[key])}
                maxLength={prop.maxLength}
                min={prop.minimum}
                max={prop.maximum}
                placeholder={placeholderFor(prop)}
                onChange={(e) =>
                  set(numeric ? (e.target.value === "" ? undefined : Number(e.target.value)) : e.target.value)
                }
                className="h-9 font-mono text-[13px]"
              />
            )}
          </Field>
        );
      })}
    </div>
  );
}
