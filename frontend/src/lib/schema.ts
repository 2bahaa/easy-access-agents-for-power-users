import type { JsonSchema } from "../api/types";

/** Default values for every property of an object schema. */
export function schemaDefaults(schema: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[key] = prop.default;
  }
  return out;
}

export function hasFields(schema: JsonSchema): boolean {
  return Object.keys(schema.properties ?? {}).length > 0;
}
