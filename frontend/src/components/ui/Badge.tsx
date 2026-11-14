import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "violet";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted ring-line",
  brand: "bg-brand-500/10 text-brand-600 ring-brand-500/20 dark:text-brand-400",
  success: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/20 dark:text-emerald-400",
  warning: "bg-amber-500/10 text-amber-700 ring-amber-500/25 dark:text-amber-400",
  danger: "bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-400",
  violet: "bg-accent-500/10 text-purple-700 ring-accent-500/20 dark:text-purple-300",
};

export function Badge({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset [&_svg]:size-3",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}
