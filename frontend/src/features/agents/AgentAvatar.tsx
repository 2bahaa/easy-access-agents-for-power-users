import { cn } from "../../lib/cn";
import { initials } from "../../lib/format";

/** FNV-1a: small, well-mixed string hash. */
function hash(text: string): number {
  let h = 0x811c9dc5;
  for (const ch of text) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

/** Two-hue gradient derived from the name: stable per agent, rarely similar between agents. */
function avatarGradient(name: string): string {
  const h = hash(name);
  const hue = h % 360;
  const second = (hue + ((h >>> 9) & 1 ? 50 : -50) + 360) % 360;
  return `linear-gradient(135deg, hsl(${hue} 78% 58%), hsl(${second} 72% 50%))`;
}

/** Deterministic gradient avatar with the agent's initials. */
export function AgentAvatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      style={{ backgroundImage: avatarGradient(name || "?") }}
      className={cn(
        "grid shrink-0 place-items-center rounded-xl font-semibold text-white shadow-md [text-shadow:0_1px_2px_rgb(0_0_0/0.25)]",
        className ?? "size-11 text-sm",
      )}
    >
      {initials(name || "?")}
    </span>
  );
}
