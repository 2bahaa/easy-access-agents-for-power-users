import { cn } from "../lib/cn";

export interface UsageChartProps {
  daily: Array<{ date: string; runs: number; failed: number }>;
  className?: string;
}

/** Daily run counts as bars (failed runs stacked in the danger tone). Prop-driven. */
export function UsageChart({ daily, className }: UsageChartProps) {
  const max = Math.max(1, ...daily.map((d) => d.runs));
  return (
    <div
      className={cn("flex h-28 items-end gap-1", className)}
      role="img"
      aria-label={`Runs per day: ${daily.map((d) => `${d.date} ${d.runs}`).join(", ")}`}
    >
      {daily.map((d) => (
        <div
          key={d.date}
          className="group relative flex h-full flex-1 flex-col justify-end"
          title={`${d.date}: ${d.runs} run(s), ${d.failed} failed`}
        >
          <div
            className="flex flex-col justify-end overflow-hidden rounded-t bg-brand-500/70"
            style={{
              height: `${(d.runs / max) * 100}%`,
              minHeight: d.runs ? 2 : 0,
            }}
          >
            <div
              className="bg-danger/80"
              style={{ height: d.runs ? `${(d.failed / d.runs) * 100}%` : 0 }}
            />
          </div>
          <div className="mt-1 h-px bg-line" />
        </div>
      ))}
    </div>
  );
}
