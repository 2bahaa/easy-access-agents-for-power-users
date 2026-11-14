import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { NavLink } from "react-router";

import type { ConversationSummary } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/States";
import { cn } from "../../lib/cn";
import { relativeTime } from "../../lib/format";

export function ConversationList({
  agentId,
  conversations,
  loading,
  activeId,
  onNew,
  onDelete,
}: {
  agentId: string;
  conversations: ConversationSummary[] | undefined;
  loading: boolean;
  activeId: string | undefined;
  onNew: () => void;
  onDelete: (conversation: ConversationSummary) => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="p-3">
        <Button variant="secondary" className="w-full" icon={<Plus className="size-4" />} onClick={onNew}>
          New chat
        </Button>
      </div>
      <p className="px-4 pb-1 text-[11px] font-semibold tracking-wider text-subtle uppercase">History</p>
      <ul aria-label="Conversations" className="scrollbar-thin min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {loading &&
          [0, 1, 2].map((i) => (
            <li key={i} className="space-y-1.5 px-2 py-2">
              <Skeleton className="h-3.5 w-3/4" />
              <Skeleton className="h-3 w-1/3" />
            </li>
          ))}
        {conversations?.length === 0 && (
          <li className="px-3 py-6 text-center text-xs text-subtle">
            <MessageSquare className="mx-auto mb-2 size-4" />
            No conversations yet.
          </li>
        )}
        {conversations?.map((c) => (
          <li key={c.id} className="group relative">
            <NavLink
              to={`/agents/${agentId}/chat/${c.id}`}
              className={cn(
                "block rounded-xl py-2 pr-9 pl-3 transition-colors",
                c.id === activeId ? "bg-brand-500/10" : "hover:bg-surface-2",
              )}
            >
              <span
                className={cn(
                  "block truncate text-sm",
                  c.id === activeId ? "font-medium text-brand-700 dark:text-brand-400" : "text-fg",
                )}
              >
                {c.title}
              </span>
              <span className="block text-[11px] text-subtle">{relativeTime(c.updated_at)}</span>
            </NavLink>
            <button
              type="button"
              aria-label={`Delete conversation ${c.title}`}
              onClick={() => onDelete(c)}
              className="absolute top-1/2 right-2 grid size-7 -translate-y-1/2 place-items-center rounded-lg text-subtle opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-600 focus-visible:opacity-100"
            >
              <Trash2 className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
