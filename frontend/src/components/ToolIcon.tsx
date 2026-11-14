import { Calculator, FileText, Wrench, type LucideIcon } from "lucide-react";
import { createElement } from "react";

const ICONS: Record<string, LucideIcon> = { calculator: Calculator, file_reader: FileText };

/** Icon for a tool by name (generic wrench for unknown tools). */
export function ToolIcon({ name, className }: { name: string; className?: string }) {
  return createElement(ICONS[name] ?? Wrench, { className, "aria-hidden": true });
}
