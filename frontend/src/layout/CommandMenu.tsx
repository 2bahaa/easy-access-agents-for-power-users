import { Command } from "cmdk";
import { Bot, MessageSquare, Moon, Monitor, Plus, Search, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { useAgents, useAllConversations } from "../api/queries";
import { useTheme } from "../lib/theme";
import { NAV_GROUPS } from "./nav";

/** ⌘K palette: navigation, quick actions, agents and recent conversations. */
export function CommandMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate();
  const { setPreference } = useTheme();
  // The shell mounts this only while open, so these queries run on demand (then stay cached).
  const agents = useAgents();
  const conversations = useAllConversations();

  const run = (fn: () => void) => {
    onOpenChange(false);
    fn();
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command menu"
      overlayClassName="fixed inset-0 z-[70] animate-fade-in bg-black/40 backdrop-blur-[2px]"
      contentClassName="fixed top-[12vh] left-1/2 z-[71] w-[min(640px,calc(100vw-32px))] -translate-x-1/2 animate-slide-up overflow-hidden rounded-2xl border border-line bg-surface shadow-pop"
    >
      <div className="flex items-center gap-2 border-b border-line px-4">
        <Search className="size-4 text-subtle" aria-hidden />
        <Command.Input
          autoFocus
          placeholder="Search pages, agents, conversations…"
          className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle"
        />
        <kbd className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-subtle">Esc</kbd>
      </div>
      <Command.List className="scrollbar-thin max-h-[min(420px,60vh)] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-8 text-center text-sm text-muted">No results.</Command.Empty>

        <Group heading="Actions">
          <Item icon={<Plus />} onSelect={() => run(() => void navigate("/agents/new"))} value="new agent create">
            New agent
          </Item>
          <Item icon={<Plus />} onSelect={() => run(() => void navigate("/skills/new"))} value="new skill create">
            New skill
          </Item>
        </Group>

        <Group heading="Navigate">
          {NAV_GROUPS.flatMap((g) => g.items).map(({ to, label, icon: Icon, keywords }) => (
            <Item key={to} icon={<Icon />} value={`${label} ${keywords ?? ""}`} onSelect={() => run(() => void navigate(to))}>
              {label}
            </Item>
          ))}
        </Group>

        {agents.data && agents.data.length > 0 && (
          <Group heading="Agents">
            {agents.data.map((a) => (
              <Item
                key={a.id}
                icon={<Bot />}
                value={`agent ${a.name} ${a.model} ${a.id}`}
                onSelect={() => run(() => void navigate(`/agents/${a.id}/chat`))}
                hint={a.model}
              >
                {a.name}
              </Item>
            ))}
          </Group>
        )}

        {conversations.data && conversations.data.length > 0 && (
          <Group heading="Recent conversations">
            {conversations.data.slice(0, 8).map((c) => (
              <Item
                key={c.id}
                icon={<MessageSquare />}
                value={`conversation ${c.title} ${c.id}`}
                onSelect={() => run(() => void navigate(`/agents/${c.agent_id}/chat/${c.id}`))}
              >
                {c.title || "Untitled conversation"}
              </Item>
            ))}
          </Group>
        )}

        <Group heading="Theme">
          <Item icon={<Monitor />} value="theme system" onSelect={() => run(() => setPreference("system"))}>
            Use system theme
          </Item>
          <Item icon={<Sun />} value="theme light" onSelect={() => run(() => setPreference("light"))}>
            Light theme
          </Item>
          <Item icon={<Moon />} value="theme dark" onSelect={() => run(() => setPreference("dark"))}>
            Dark theme
          </Item>
        </Group>
      </Command.List>
    </Command.Dialog>
  );
}

function Group({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="mb-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-subtle [&_[cmdk-group-heading]]:uppercase"
    >
      {children}
    </Command.Group>
  );
}

function Item({
  icon,
  children,
  hint,
  value,
  onSelect,
}: {
  icon: ReactNode;
  children: ReactNode;
  hint?: string;
  value: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-fg data-[selected=true]:bg-brand-500/10 data-[selected=true]:text-brand-700 dark:data-[selected=true]:text-brand-400 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-subtle"
    >
      {icon}
      <span className="flex-1 truncate">{children}</span>
      {hint && <span className="font-mono text-[11px] text-subtle">{hint}</span>}
    </Command.Item>
  );
}
