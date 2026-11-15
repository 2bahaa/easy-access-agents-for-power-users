import { Check, Pencil, ShieldQuestion, X } from "lucide-react";
import { useState } from "react";

import type { Approval } from "../api/types";
import { prettyToolName } from "../lib/tools";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Textarea } from "./ui/Field";

export interface ApprovalCardProps {
  approval: Approval;
  onDecide: (decision: { approve: boolean; args?: Record<string, unknown>; note?: string }) => void;
  busy?: boolean;
  /** Read-only (e.g. the viewer may not decide). */
  disabled?: boolean;
  /** Extra context line (agent name, conversation link…). */
  context?: React.ReactNode;
}

/** A held tool call: inspect (and optionally edit) the arguments, then approve or reject.
 * Prop-driven: the decision is reported through `onDecide`. */
export function ApprovalCard({ approval, onDecide, busy, disabled, context }: ApprovalCardProps) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(JSON.stringify(approval.args, null, 2));
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const approve = () => {
    if (!editing) return onDecide({ approve: true });
    try {
      const parsed: unknown = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
      setError(null);
      onDecide({ approve: true, args: parsed as Record<string, unknown> });
    } catch {
      setError("Arguments must be a JSON object.");
    }
  };

  return (
    <article
      aria-label={`Approval for ${prettyToolName(approval.tool_name)}`}
      className="rounded-2xl border border-warning/35 bg-warning/5 p-4"
    >
      <header className="flex flex-wrap items-center gap-2">
        <ShieldQuestion className="size-4 text-warning" />
        <h3 className="text-sm font-semibold">{prettyToolName(approval.tool_name)} wants to run</h3>
        <Badge tone="warning">needs approval</Badge>
        <span className="ml-auto text-xs text-subtle">
          expires {new Date(approval.expires_at).toLocaleString()}
        </span>
      </header>
      {context && <div className="mt-1 text-xs text-muted">{context}</div>}
      {editing ? (
        <Textarea
          aria-label="Arguments (JSON)"
          className="mt-3 font-mono text-xs"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
        />
      ) : (
        <pre className="mt-3 overflow-x-auto rounded-lg bg-surface p-2.5 font-mono text-xs">
          {JSON.stringify(approval.args, null, 2)}
        </pre>
      )}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      {!disabled && (
        <>
          <input
            aria-label="Note (optional)"
            placeholder="Note for the agent (optional)"
            className="mt-3 h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm outline-none focus:border-brand-500"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" size="sm" icon={<Check className="size-4" />} loading={busy} onClick={approve}>
              {editing ? "Approve with changes" : "Approve"}
            </Button>
            <Button size="sm" icon={<X className="size-4" />} disabled={busy} onClick={() => onDecide({ approve: false, note })}>
              Reject
            </Button>
            {!editing && (
              <Button size="sm" variant="ghost" icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>
                Edit arguments
              </Button>
            )}
          </div>
        </>
      )}
    </article>
  );
}
