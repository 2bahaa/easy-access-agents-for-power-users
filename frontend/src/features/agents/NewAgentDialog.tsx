import { FilePlus2, Sparkles, X } from "lucide-react";
import { Link } from "react-router";

import { useAgentTemplates } from "../../api/queries";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/States";

/** Start from scratch or from a built-in template (the model is always chosen by the user). */
export function NewAgentDialog({ onClose }: { onClose: () => void }) {
  const templates = useAgentTemplates();
  return (
    <div className="fixed inset-0 z-[55] grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="New agent">
      <button type="button" aria-label="Close" className="absolute inset-0 animate-fade-in bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-2xl animate-slide-up rounded-2xl border border-line bg-surface shadow-pop">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold">Create an agent</h2>
            <p className="text-sm text-muted">Start blank or from a template you can adjust.</p>
          </div>
          <Button size="sm" variant="ghost" aria-label="Close dialog" icon={<X className="size-4" />} onClick={onClose} />
        </header>
        <div className="grid max-h-[70vh] gap-3 overflow-y-auto p-5 sm:grid-cols-2">
          <Link
            to="/agents/new"
            onClick={onClose}
            className="flex gap-3 rounded-xl border border-dashed border-line-strong p-4 transition-colors hover:border-brand-500 hover:bg-brand-500/5"
          >
            <FilePlus2 className="mt-0.5 size-5 shrink-0 text-subtle" />
            <span>
              <span className="block text-sm font-semibold">Blank agent</span>
              <span className="block text-xs text-muted">Write the instructions yourself.</span>
            </span>
          </Link>
          {templates.isPending &&
            [0, 1, 2].map((i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
          {templates.data?.map((t) => (
            <Link
              key={t.id}
              to={`/agents/new?template=${encodeURIComponent(t.id)}`}
              onClick={onClose}
              className="flex gap-3 rounded-xl border border-line p-4 transition-colors hover:border-brand-500 hover:bg-brand-500/5"
            >
              <Sparkles className="mt-0.5 size-5 shrink-0 text-brand-600 dark:text-brand-400" />
              <span className="min-w-0">
                <span className="flex items-center gap-2 text-sm font-semibold">
                  {t.name} <Badge>{t.category}</Badge>
                </span>
                <span className="mt-0.5 block text-xs text-muted">{t.description}</span>
                {t.tools.length > 0 && (
                  <span className="mt-1.5 block text-[11px] text-subtle">Tools: {t.tools.map((x) => x.name).join(", ")}</span>
                )}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
